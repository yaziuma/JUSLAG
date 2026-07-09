"""build_period_quant_output.py

複数期間 × 戦略 の定量出力スクリプト。
- 指定期間 + trailing 5期間 (full/5y/3y/2y/1y) を自動付加
- 6戦略必須 + 3戦略オプション
- 日次・月次・年次・期間サマリ・ベースライン比較 の 5 CSV + 1 MD

Usage:
    uv run python scripts/build_period_quant_output.py \
        --periods '[{"label":"p01","start":"2026-05-01","end":"2026-06-15"}]' \
        --output-dir outputs/period_quant/job123 \
        [--include-optional]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from juslag.config import (
    JP_CYCLICAL, JP_TICKERS, US_CYCLICAL,
    US_TICKERS as _US_TICKERS_FULL, TaxConfig,
)
from juslag.data_loader import build_joint_cc, compute_returns, fetch_data
from juslag.metrics import apply_tax_model
from juslag.prior import build_prior_eigenvectors, build_prior_exposure
from juslag.regime import build_regime_frame
from juslag.signal import generate_signals

_JST = ZoneInfo("Asia/Tokyo")

_EXCLUDE = {"XLC", "XLRE"}
US_TICKERS = {k: v for k, v in _US_TICKERS_FULL.items() if k not in _EXCLUDE}
US_CYCLICAL_EFF = {k: v for k, v in US_CYCLICAL.items() if k not in _EXCLUDE}

SAMPLE_START  = "2013-01-01"
PRETRAIN_END  = "2021-12-31"
PRICE_MODE    = "raw"
FILL_POLICY   = "strict"
Q             = 0.3
WINDOW_L      = 60
K_FACTORS     = 3
LAMBDA_REG    = 0.9
MIN_LONG      = 0.10
MAX_SHORT     = -0.10
COMMISSION_RT = 0.001

TAX_CFG = TaxConfig(enabled=True, tax_model="annual_net", tax_rate=0.20315, loss_carryforward_years=3)

TRAILING_PERIODS: list[dict[str, str]] = [
    {"label": "full_period",  "days": "full"},
    {"label": "trailing_5y",  "days": str(252 * 5)},
    {"label": "trailing_3y",  "days": str(252 * 3)},
    {"label": "trailing_2y",  "days": str(252 * 2)},
    {"label": "trailing_1y",  "days": str(252)},
]

CORE_STRATEGIES: dict[str, dict[str, Any]] = {
    "S01_CurrOC":    {"dir": "orig",       "horizon": "oc", "filter": None,                "name": "現行OC"},
    "S08_GapOvht05": {"dir": "orig",       "horizon": "oc", "filter": "gap_aligned_0.005", "name": "GapOvht除外OC"},
    "S09_LGapFlt05": {"dir": "orig",       "horizon": "oc", "filter": "long_gap_0.005",    "name": "LGap除外OC"},
    "S10_ShortOnly": {"dir": "short_only", "horizon": "oc", "filter": None,                "name": "SHORT単独OC"},
    "S02_FlipL_OC":  {"dir": "flip_l",     "horizon": "oc", "filter": None,                "name": "LONG反転OC"},
    "S03_CurrCC":    {"dir": "orig",       "horizon": "cc", "filter": None,                "name": "現行CC"},
}
OPT_STRATEGIES: dict[str, dict[str, Any]] = {
    "S04_FlipL_CC":  {"dir": "flip_l",    "horizon": "cc", "filter": None, "name": "LONG反転CC"},
    "S05_CurrOO":    {"dir": "orig",      "horizon": "oo", "filter": None, "name": "現行OO"},
    "S06_Curr1D":    {"dir": "orig",      "horizon": "1d", "filter": None, "name": "現行1D持越"},
}
SC_ORDER = list(CORE_STRATEGIES.keys()) + list(OPT_STRATEGIES.keys())
NA = "NA"


# ── Signal cache ──────────────────────────────────────────────────────────────

_SIGNAL_CACHE_PATH = Path("outputs/signal_cache.pkl")


def _load_or_generate_signals() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (signal_df, jp_close, jp_open, jp_oc, jp_cc, us_cc) with cache."""
    sample_end = (datetime.now(_JST).date() + pd.Timedelta(days=1)).isoformat()
    try:
        us_close, jp_close, jp_open = fetch_data(
            list(US_TICKERS.keys()), list(JP_TICKERS.keys()),
            SAMPLE_START, sample_end, price_mode=PRICE_MODE,
        )
    except Exception as exc:
        raise RuntimeError(f"データ取得失敗: {exc}") from exc

    us_cc, jp_oc, jp_cc = compute_returns(us_close, jp_close, jp_open)

    us_tks = us_close.columns.tolist()
    jp_tks = jp_close.columns.tolist()
    v0 = build_prior_eigenvectors(
        us_tks, jp_tks,
        {k: v for k, v in US_CYCLICAL_EFF.items() if k in us_tks},
        {k: v for k, v in JP_CYCLICAL.items() if k in jp_tks},
    )
    jcc, _ = build_joint_cc(us_cc, jp_cc, fill_policy=FILL_POLICY)
    c0 = build_prior_exposure(jcc.loc[:PRETRAIN_END], v0)
    signal_df = generate_signals(us_cc, jp_cc, c0, l=WINDOW_L, k=K_FACTORS, lam=LAMBDA_REG)
    return signal_df, jp_close, jp_open, jp_oc, jp_cc, us_cc


# ── Strategy return computation ───────────────────────────────────────────────

def _apply_direction_detail(
    sig_c: pd.Series,
    ret_c: pd.Series,
    direction: str,
    filter_name: str | None,
    gap_c: pd.Series | None,
) -> dict[str, Any]:
    lo_c = sig_c.quantile(Q)
    hi_c = sig_c.quantile(1.0 - Q)
    lm_base = (sig_c >= hi_c) & (sig_c >= MIN_LONG)
    sm_base = (sig_c <= lo_c) & (sig_c <= MAX_SHORT)
    cand_l = int(lm_base.sum())
    cand_s = int(sm_base.sum())

    lm = lm_base.copy()
    sm = sm_base.copy()
    gap_filtered = False

    if filter_name == "gap_aligned_0.005" and gap_c is not None:
        ga = gap_c.reindex(lm.index).fillna(0)
        lm = lm & (ga <= 0.005)
        sm = sm & (ga >= -0.005)
        if cand_l > 0 or cand_s > 0:
            gap_filtered = (int(lm.sum()) < cand_l) or (int(sm.sum()) < cand_s)
    elif filter_name == "long_gap_0.005" and gap_c is not None:
        ga = gap_c.reindex(lm.index).fillna(0)
        lm = lm & (ga <= 0.005)
        if cand_l > 0:
            gap_filtered = int(lm.sum()) < cand_l

    n_l, n_s = int(lm.sum()), int(sm.sum())

    if n_l == 0 and n_s == 0:
        if cand_l == 0 and cand_s == 0:
            skip = "no_threshold_candidates"
        elif gap_filtered:
            skip = "gap_filter_removed_all"
        else:
            skip = "no_candidates"
        return {
            "gross": 0.0, "long_contrib": 0.0, "short_contrib": 0.0,
            "tradeable": False, "skip_reason": skip,
            "adopt_long": 0, "adopt_short": 0, "cand_long": cand_l, "cand_short": cand_s,
        }

    if direction == "orig":
        lc = float((ret_c[lm] / n_l).sum()) if n_l else 0.0
        sc = float((-ret_c[sm] / n_s).sum()) if n_s else 0.0
    elif direction == "flip_l":
        lc = float((-ret_c[lm] / n_l).sum()) if n_l else 0.0
        sc = float((-ret_c[sm] / n_s).sum()) if n_s else 0.0
    elif direction == "short_only":
        lc = 0.0
        sc = float((-ret_c[sm] / n_s).sum()) if n_s else 0.0
    else:
        return {"gross": 0.0, "long_contrib": 0.0, "short_contrib": 0.0,
                "tradeable": False, "skip_reason": "unknown_direction",
                "adopt_long": 0, "adopt_short": 0, "cand_long": cand_l, "cand_short": cand_s}

    if n_l > 0 and n_s > 0:
        gross = 0.5 * lc + 0.5 * sc
    elif n_l > 0:
        gross = lc
    else:
        gross = sc

    return {
        "gross": gross, "long_contrib": lc, "short_contrib": sc,
        "tradeable": True, "skip_reason": None,
        "adopt_long": n_l, "adopt_short": n_s,
        "cand_long": cand_l, "cand_short": cand_s,
    }


def compute_detailed_strategy_returns(
    signal_df: pd.DataFrame,
    jp_close: pd.DataFrame,
    jp_open: pd.DataFrame,
    jp_oc: pd.DataFrame,
    jp_cc: pd.DataFrame,
    strategies: dict[str, dict[str, Any]],
) -> pd.DataFrame:
    """日次×戦略 の詳細リターンを全期間分計算。"""
    intraday_df = jp_oc.shift(-1)
    cc_next     = jp_cc.shift(-1)
    gap_df      = jp_open.shift(-1) / jp_close - 1.0
    oo_ret      = jp_open.shift(-2) / jp_open.shift(-1) - 1.0
    oneday_hold = jp_close.shift(-2) / jp_open.shift(-1) - 1.0

    records: list[dict[str, Any]] = []
    for t in signal_df.index:
        sig = signal_df.loc[t].dropna()
        if len(sig) < 3:
            for sc_id in strategies:
                records.append({"date": t, "strategy_id": sc_id,
                                 "gross": 0.0, "long_contrib": 0.0, "short_contrib": 0.0,
                                 "tradeable": False, "skip_reason": "insufficient_signal",
                                 "adopt_long": 0, "adopt_short": 0, "cand_long": 0, "cand_short": 0})
            continue

        def _safe(df: pd.DataFrame) -> pd.Series:
            if t not in df.index:
                return pd.Series(dtype=float)
            return df.loc[t, sig.index].dropna()

        rets = {
            "oc": _safe(intraday_df),
            "cc": _safe(cc_next),
            "oo": _safe(oo_ret),
            "1d": _safe(oneday_hold),
        }
        gap_c_full = _safe(gap_df)

        for sc_id, cfg in strategies.items():
            ret = rets[cfg["horizon"]]
            if ret.empty:
                records.append({"date": t, "strategy_id": sc_id,
                                 "gross": 0.0, "long_contrib": 0.0, "short_contrib": 0.0,
                                 "tradeable": False, "skip_reason": "no_jp_return_data",
                                 "adopt_long": 0, "adopt_short": 0, "cand_long": 0, "cand_short": 0})
                continue
            common = sig.index.intersection(ret.index)
            if len(common) < 2:
                records.append({"date": t, "strategy_id": sc_id,
                                 "gross": 0.0, "long_contrib": 0.0, "short_contrib": 0.0,
                                 "tradeable": False, "skip_reason": "too_few_common_tickers",
                                 "adopt_long": 0, "adopt_short": 0, "cand_long": 0, "cand_short": 0})
                continue
            sig_c = sig[common]
            ret_c = ret[common]
            gap_c = gap_c_full.reindex(common).fillna(0) if not gap_c_full.empty else None
            d = _apply_direction_detail(sig_c, ret_c, cfg["dir"], cfg["filter"], gap_c)
            d["date"] = t
            d["strategy_id"] = sc_id
            records.append(d)

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values(["date", "strategy_id"]).reset_index(drop=True)


# ── JP / signal / regime features ────────────────────────────────────────────

def compute_jp_daily_features(
    signal_df: pd.DataFrame,
    jp_close: pd.DataFrame,
    jp_open: pd.DataFrame,
    jp_oc: pd.DataFrame,
    jp_cc: pd.DataFrame,
) -> pd.DataFrame:
    gap_df      = jp_open.shift(-1) / jp_close - 1.0
    intraday_df = jp_oc.shift(-1)
    cc_next     = jp_cc.shift(-1)

    rows: list[dict[str, Any]] = []
    for t in signal_df.index:
        if t not in gap_df.index or t not in intraday_df.index:
            continue
        sig = signal_df.loc[t].dropna()
        if len(sig) < 3:
            continue
        lo = sig.quantile(Q); hi = sig.quantile(1.0 - Q)
        long_tks  = sig.index[sig >= hi].tolist()
        short_tks = sig.index[sig <= lo].tolist()

        gap_all   = gap_df.loc[t, sig.index].dropna()
        oc_all    = intraday_df.loc[t, sig.index].dropna()
        cc_all    = cc_next.loc[t, sig.index].dropna() if t in cc_next.index else pd.Series(dtype=float)
        gap_long  = gap_df.loc[t, long_tks].dropna()  if long_tks  else pd.Series(dtype=float)
        gap_short = gap_df.loc[t, short_tks].dropna() if short_tks else pd.Series(dtype=float)

        oc_mean = float(oc_all.mean()) if not oc_all.empty else float("nan")
        gap_mean = float(gap_all.mean()) if not gap_all.empty else float("nan")
        rows.append({
            "date":                   t,
            "jp_next_open_gap_mean":  gap_mean,
            "jp_oc_mean":             oc_mean,
            "jp_cc_mean":             float(cc_all.mean()) if not cc_all.empty else float("nan"),
            "jp_gap_to_oc_reversal":  oc_mean - gap_mean if not (np.isnan(oc_mean) or np.isnan(gap_mean)) else float("nan"),
            "jp_long_gap_mean":       float(gap_long.mean())  if not gap_long.empty  else float("nan"),
            "jp_short_gap_mean":      float(gap_short.mean()) if not gap_short.empty else float("nan"),
        })

    df = pd.DataFrame(rows).set_index("date")
    df.index = pd.to_datetime(df.index)
    return df


def compute_signal_daily_features(signal_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for t in signal_df.index:
        sig = signal_df.loc[t].dropna()
        if len(sig) < 3:
            continue
        lo = sig.quantile(Q); hi = sig.quantile(1.0 - Q)
        cand_l  = sig[sig >= hi]; cand_s = sig[sig <= lo]
        adopt_l = cand_l[cand_l >= MIN_LONG]; adopt_s = cand_s[cand_s <= MAX_SHORT]
        cand_str  = float(cand_l.mean()  - cand_s.mean())  if not cand_l.empty  and not cand_s.empty  else float("nan")
        adopt_str = float(adopt_l.mean() - adopt_s.mean()) if not adopt_l.empty and not adopt_s.empty else float("nan")
        rows.append({
            "date":                      t,
            "trade_signal_strength":     adopt_str,
            "candidate_signal_strength": cand_str,
            "adopted_signal_strength":   adopt_str,
        })
    df = pd.DataFrame(rows).set_index("date")
    df.index = pd.to_datetime(df.index)
    return df


# ── Period slicing ─────────────────────────────────────────────────────────────

def _resolve_period(label: str, days_str: str, signal_df: pd.DataFrame) -> tuple[str, str]:
    if days_str == "full":
        return str(signal_df.index[0].date()), str(signal_df.index[-1].date())
    n = int(days_str)
    idx = signal_df.index[-n:] if len(signal_df) >= n else signal_df.index
    return str(idx[0].date()), str(idx[-1].date())


def _slice_strat(strat_df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    mask = (strat_df["date"] >= pd.Timestamp(start)) & (strat_df["date"] <= pd.Timestamp(end))
    return strat_df[mask].copy()


# ── Net return computation ─────────────────────────────────────────────────────

def _net_series(
    gross: pd.Series,          # indexed by date
    tradeable: pd.Series,      # bool indexed by date
) -> tuple[pd.Series, pd.Series]:
    net_pt = gross.copy()
    net_pt.loc[tradeable] -= COMMISSION_RT
    if net_pt.empty or net_pt.isna().all():
        return net_pt, net_pt.copy()
    try:
        net_at = apply_tax_model(net_pt.dropna(), TAX_CFG)["net_after_tax_return"].reindex(net_pt.index).fillna(0.0)
    except Exception:
        net_at = net_pt.copy()
    return net_pt, net_at


# ── Daily assembly ────────────────────────────────────────────────────────────

def build_period_daily(
    strat_rows: pd.DataFrame,
    sig_feat_df: pd.DataFrame,
    jp_feat_df: pd.DataFrame,
    regime_df: pd.DataFrame,
    strategies: dict[str, dict[str, Any]],
    period_label: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    sliced = _slice_strat(strat_rows, start, end)
    if sliced.empty:
        return pd.DataFrame()

    records: list[dict[str, Any]] = []
    for sc_id, cfg in strategies.items():
        sc_rows = sliced[sliced["strategy_id"] == sc_id].copy()
        if sc_rows.empty:
            continue
        sc_rows = sc_rows.set_index("date").sort_index()
        gross     = sc_rows["gross"]
        tradeable = sc_rows["tradeable"]
        net_pt, net_at = _net_series(gross, tradeable)

        for t, row in sc_rows.iterrows():
            t_str = str(t.date())
            def _jp(col: str) -> Any:
                if t in jp_feat_df.index and col in jp_feat_df.columns:
                    v = jp_feat_df.loc[t, col]
                    return float(v) if not (isinstance(v, float) and np.isnan(v)) else NA
                return NA
            def _sig(col: str) -> Any:
                if t in sig_feat_df.index and col in sig_feat_df.columns:
                    v = sig_feat_df.loc[t, col]
                    return float(v) if not (isinstance(v, float) and np.isnan(v)) else NA
                return NA
            def _reg(col: str) -> Any:
                if t in regime_df.index and col in regime_df.columns:
                    return str(regime_df.loc[t, col])
                return NA

            g   = float(row["gross"])
            npt = float(net_pt.get(t, 0.0))
            nat = float(net_at.get(t, 0.0))
            records.append({
                "date":                      t_str,
                "period_label":              period_label,
                "strategy_id":               sc_id,
                "strategy_name":             cfg["name"],
                "gross_return_pct":          round(g * 100, 6),
                "net_pre_tax_return_pct":    round(npt * 100, 6),
                "net_after_tax_return_pct":  round(nat * 100, 6),
                "long_contribution_pct":     round(float(row["long_contrib"]) * 100, 6),
                "short_contribution_pct":    round(float(row["short_contrib"]) * 100, 6),
                "tradeable":                 bool(row["tradeable"]),
                "skip_reason":               str(row["skip_reason"]) if row["skip_reason"] is not None else NA,
                "candidate_long_count":      int(row["cand_long"]),
                "candidate_short_count":     int(row["cand_short"]),
                "adopted_long_count":        int(row["adopt_long"]),
                "adopted_short_count":       int(row["adopt_short"]),
                "trade_signal_strength":     _sig("trade_signal_strength"),
                "candidate_signal_strength": _sig("candidate_signal_strength"),
                "adopted_signal_strength":   _sig("adopted_signal_strength"),
                "jp_next_open_gap_mean":     _jp("jp_next_open_gap_mean"),
                "jp_oc_mean":               _jp("jp_oc_mean"),
                "jp_cc_mean":               _jp("jp_cc_mean"),
                "jp_gap_to_oc_reversal":    _jp("jp_gap_to_oc_reversal"),
                "jp_long_gap_mean":         _jp("jp_long_gap_mean"),
                "jp_short_gap_mean":        _jp("jp_short_gap_mean"),
                "trend_regime":             _reg("trend_regime"),
                "vol_regime":               _reg("vol_regime"),
                "rotation_regime":          _reg("rotation_regime"),
            })

    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records)


# ── Monthly / Yearly aggregation ──────────────────────────────────────────────

def _max_consec(arr: np.ndarray, positive: bool) -> int:
    mx = cur = 0
    for r in arr:
        if (r > 0) == positive:
            cur += 1; mx = max(mx, cur)
        else:
            cur = 0
    return mx


def _compound(arr: np.ndarray) -> float:
    return float(np.prod(1 + arr / 100) - 1) * 100


def _mdd(arr: np.ndarray) -> float:
    if len(arr) == 0:
        return 0.0
    eq   = np.cumprod(1 + arr / 100)
    peak = np.maximum.accumulate(eq)
    dd   = (eq - peak) / peak
    return float(dd.min()) * 100


def aggregate_monthly(daily_df: pd.DataFrame) -> pd.DataFrame:
    if daily_df.empty:
        return pd.DataFrame()
    daily_df = daily_df.copy()
    daily_df["_ym"] = pd.to_datetime(daily_df["date"]).dt.to_period("M").astype(str)
    rows: list[dict[str, Any]] = []
    for (period_label, sc_id, ym), grp in daily_df.groupby(["period_label", "strategy_id", "_ym"]):
        ga  = grp["gross_return_pct"].values.astype(float)
        nat = grp["net_after_tax_return_pct"].values.astype(float)
        rows.append({
            "year_month":               ym,
            "period_label":             period_label,
            "strategy_id":              sc_id,
            "strategy_name":            grp["strategy_name"].iloc[0],
            "n_days":                   len(ga),
            "gross_avg_pct":            round(float(np.mean(ga)), 6),
            "gross_cumulative_pct":     round(_compound(ga), 6),
            "net_after_tax_avg_pct":    round(float(np.mean(nat)), 6),
            "net_after_tax_cumulative_pct": round(_compound(nat), 6),
            "win_rate":                 round(float(np.mean(ga > 0)), 4),
            "plus_day_ratio":           round(float(np.mean(ga > 0)), 4),
            "long_contribution_sum_pct": round(float(grp["long_contribution_pct"].values.astype(float).sum()), 6),
            "short_contribution_sum_pct": round(float(grp["short_contribution_pct"].values.astype(float).sum()), 6),
            "max_drawdown_pct":         round(_mdd(ga), 4),
        })
    return pd.DataFrame(rows)


def aggregate_yearly(daily_df: pd.DataFrame) -> pd.DataFrame:
    if daily_df.empty:
        return pd.DataFrame()
    daily_df = daily_df.copy()
    daily_df["_yr"] = pd.to_datetime(daily_df["date"]).dt.year
    rows: list[dict[str, Any]] = []
    for (period_label, sc_id, yr), grp in daily_df.groupby(["period_label", "strategy_id", "_yr"]):
        ga  = grp["gross_return_pct"].values.astype(float)
        nat = grp["net_after_tax_return_pct"].values.astype(float)
        rows.append({
            "year":                     int(yr),
            "period_label":             period_label,
            "strategy_id":              sc_id,
            "strategy_name":            grp["strategy_name"].iloc[0],
            "n_days":                   len(ga),
            "gross_avg_pct":            round(float(np.mean(ga)), 6),
            "gross_cumulative_pct":     round(_compound(ga), 6),
            "net_after_tax_avg_pct":    round(float(np.mean(nat)), 6),
            "net_after_tax_cumulative_pct": round(_compound(nat), 6),
            "win_rate":                 round(float(np.mean(ga > 0)), 4),
            "plus_day_ratio":           round(float(np.mean(ga > 0)), 4),
            "long_contribution_sum_pct": round(float(grp["long_contribution_pct"].values.astype(float).sum()), 6),
            "short_contribution_sum_pct": round(float(grp["short_contribution_pct"].values.astype(float).sum()), 6),
            "max_drawdown_pct":         round(_mdd(ga), 4),
        })
    return pd.DataFrame(rows)


# ── Period summary ────────────────────────────────────────────────────────────

def build_period_summary(
    daily_df: pd.DataFrame,
    period_label: str,
    start: str,
    end: str,
    strategies: dict[str, dict[str, Any]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for sc_id, cfg in strategies.items():
        grp = daily_df[(daily_df["strategy_id"] == sc_id) & (daily_df["period_label"] == period_label)]
        if grp.empty:
            rows.append({
                "period_label": period_label, "start_date": start, "end_date": end,
                "strategy_id": sc_id, "strategy_name": cfg["name"],
                "n_days": 0, "notes": "no_data",
                **{k: NA for k in [
                    "gross_avg_pct","gross_cumulative_pct","net_pre_tax_avg_pct","net_pre_tax_cumulative_pct",
                    "net_after_tax_avg_pct","net_after_tax_cumulative_pct","median_return_pct",
                    "win_rate","plus_day_ratio","max_drawdown_pct","max_consecutive_losses","max_consecutive_wins",
                    "long_contribution_avg_pct","short_contribution_avg_pct",
                ]},
            })
            continue
        ga   = grp["gross_return_pct"].values.astype(float)
        npt  = grp["net_pre_tax_return_pct"].values.astype(float)
        nat  = grp["net_after_tax_return_pct"].values.astype(float)
        lc   = grp["long_contribution_pct"].values.astype(float)
        sc   = grp["short_contribution_pct"].values.astype(float)
        rows.append({
            "period_label":               period_label,
            "start_date":                 start,
            "end_date":                   end,
            "strategy_id":                sc_id,
            "strategy_name":              cfg["name"],
            "n_days":                     len(ga),
            "gross_avg_pct":              round(float(np.mean(ga)), 6),
            "gross_cumulative_pct":       round(_compound(ga), 6),
            "net_pre_tax_avg_pct":        round(float(np.mean(npt)), 6),
            "net_pre_tax_cumulative_pct": round(_compound(npt), 6),
            "net_after_tax_avg_pct":      round(float(np.mean(nat)), 6),
            "net_after_tax_cumulative_pct": round(_compound(nat), 6),
            "median_return_pct":          round(float(np.median(ga)), 6),
            "win_rate":                   round(float(np.mean(ga > 0)), 4),
            "plus_day_ratio":             round(float(np.mean(ga > 0)), 4),
            "max_drawdown_pct":           round(_mdd(ga), 4),
            "max_consecutive_losses":     _max_consec(ga, False),
            "max_consecutive_wins":       _max_consec(ga, True),
            "long_contribution_avg_pct":  round(float(np.mean(lc)), 6),
            "short_contribution_avg_pct": round(float(np.mean(sc)), 6),
            "notes":                      NA,
        })
    return pd.DataFrame(rows)


# ── Baseline comparison ───────────────────────────────────────────────────────

def build_baseline_comparison(summary_df: pd.DataFrame) -> pd.DataFrame:
    baseline = "S01_CurrOC"
    rows: list[dict[str, Any]] = []
    for period_label, grp in summary_df.groupby("period_label"):
        base_row = grp[grp["strategy_id"] == baseline]
        if base_row.empty:
            continue
        b = base_row.iloc[0]
        def _bval(col: str) -> float | str:
            v = b.get(col, NA)
            return float(v) if v != NA else NA
        for _, row in grp.iterrows():
            def _diff(col: str) -> Any:
                rv = row.get(col, NA); bv = _bval(col)
                if rv == NA or bv == NA:
                    return NA
                try:
                    return round(float(rv) - float(bv), 6)
                except Exception:
                    return NA
            rows.append({
                "period_label":                     period_label,
                "start_date":                       row.get("start_date", NA),
                "end_date":                         row.get("end_date", NA),
                "strategy_id":                      row["strategy_id"],
                "strategy_name":                    row["strategy_name"],
                "delta_gross_avg_vs_curr_oc":       _diff("gross_avg_pct"),
                "delta_gross_cumulative_vs_curr_oc": _diff("gross_cumulative_pct"),
                "delta_net_after_avg_vs_curr_oc":   _diff("net_after_tax_avg_pct"),
                "delta_net_after_cumulative_vs_curr_oc": _diff("net_after_tax_cumulative_pct"),
                "delta_win_rate_vs_curr_oc":        _diff("win_rate"),
                "delta_mdd_vs_curr_oc":             _diff("max_drawdown_pct"),
                "delta_long_contribution_vs_curr_oc":  _diff("long_contribution_avg_pct"),
                "delta_short_contribution_vs_curr_oc": _diff("short_contribution_avg_pct"),
            })
    return pd.DataFrame(rows)


# ── Markdown report ───────────────────────────────────────────────────────────

def build_markdown_report(
    created_at: str,
    all_periods: list[dict[str, str]],
    summary_df: pd.DataFrame,
    baseline_df: pd.DataFrame,
    monthly_df: pd.DataFrame,
    yearly_df: pd.DataFrame,
) -> str:
    def _fp(v: Any, d: int = 3) -> str:
        if v == NA or v is None or (isinstance(v, float) and np.isnan(v)):
            return "NA"
        return f"{float(v):+.{d}f}%"

    lines: list[str] = [
        f"# 期間定量出力レポート ({created_at})",
        "",
        "## 1. 対象期間",
        "",
        "| # | period_label | start_date | end_date |",
        "| --- | --- | --- | --- |",
    ]
    for i, p in enumerate(all_periods, 1):
        lines.append(f"| {i} | {p['label']} | {p['start']} | {p['end']} |")
    lines.append("")

    # Period summary table
    lines += [
        "## 2. 期間サマリ",
        "",
        "| period_label | strategy | gross_cum% | net_at_cum% | win_rate | mdd% | n_days |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for _, row in summary_df.sort_values(["period_label", "strategy_id"],
                                          key=lambda x: x.map({v: i for i, v in enumerate(
                                              [p["label"] for p in all_periods] + ["__z"]
                                          )}) if x.name == "period_label" else x).iterrows():
        lines.append(
            f"| {row['period_label']} | {row['strategy_name']} "
            f"| {_fp(row['gross_cumulative_pct'])} "
            f"| {_fp(row['net_after_tax_cumulative_pct'])} "
            f"| {_fp(row['win_rate'], 1)} "
            f"| {_fp(row['max_drawdown_pct'])} "
            f"| {row['n_days']} |"
        )
    lines.append("")

    # Baseline comparison
    lines += [
        "## 3. ベースライン比較（vs 現行OC）",
        "",
        "| period_label | strategy | Δnet_at_cum% | Δwin_rate% | Δmdd% |",
        "| --- | --- | --- | --- | --- |",
    ]
    for _, row in baseline_df.iterrows():
        lines.append(
            f"| {row['period_label']} | {row['strategy_name']} "
            f"| {_fp(row['delta_net_after_cumulative_vs_curr_oc'])} "
            f"| {_fp(row['delta_win_rate_vs_curr_oc'], 1)} "
            f"| {_fp(row['delta_mdd_vs_curr_oc'])} |"
        )
    lines.append("")

    # Monthly tables per period
    lines += ["## 4. 月次集計", ""]
    for p in all_periods:
        lbl = p["label"]
        lines.append(f"### {lbl}")
        mo = monthly_df[monthly_df["period_label"] == lbl]
        if mo.empty:
            lines += ["*データなし*", ""]
            continue
        lines += [
            "| year_month | strategy | gross_cum% | net_at_cum% | win_rate | mdd% | n |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for _, row in mo.sort_values(["year_month", "strategy_id"]).iterrows():
            lines.append(
                f"| {row['year_month']} | {row['strategy_name']} "
                f"| {_fp(row['gross_cumulative_pct'])} "
                f"| {_fp(row['net_after_tax_cumulative_pct'])} "
                f"| {_fp(row['win_rate'], 1)} "
                f"| {_fp(row['max_drawdown_pct'])} "
                f"| {row['n_days']} |"
            )
        lines.append("")

    # Yearly tables per period
    lines += ["## 5. 年次集計", ""]
    for p in all_periods:
        lbl = p["label"]
        lines.append(f"### {lbl}")
        yr = yearly_df[yearly_df["period_label"] == lbl]
        if yr.empty:
            lines += ["*データなし*", ""]
            continue
        lines += [
            "| year | strategy | gross_cum% | net_at_cum% | win_rate | mdd% | n |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for _, row in yr.sort_values(["year", "strategy_id"]).iterrows():
            lines.append(
                f"| {row['year']} | {row['strategy_name']} "
                f"| {_fp(row['gross_cumulative_pct'])} "
                f"| {_fp(row['net_after_tax_cumulative_pct'])} "
                f"| {_fp(row['win_rate'], 1)} "
                f"| {_fp(row['max_drawdown_pct'])} "
                f"| {row['n_days']} |"
            )
        lines.append("")

    return "\n".join(lines) + "\n"


# ── SC ordering helper ────────────────────────────────────────────────────────

def _order_df(df: pd.DataFrame, period_order: list[str]) -> pd.DataFrame:
    if "strategy_id" in df.columns:
        sc_idx = {sc: i for i, sc in enumerate(SC_ORDER)}
        df = df.copy()
        df["_sc_order"] = df["strategy_id"].map(sc_idx).fillna(99)
        df = df.sort_values(["_sc_order"]).drop(columns=["_sc_order"])
    return df


# ── Main ──────────────────────────────────────────────────────────────────────

def run(
    user_periods: list[dict[str, str]],
    output_dir: Path,
    include_optional: bool = False,
    no_trailing: bool = False,
) -> dict[str, Any]:
    today = datetime.now(_JST).date().isoformat()
    strategies = {**CORE_STRATEGIES, **(OPT_STRATEGIES if include_optional else {})}

    # ── 1. データロード ──────────────────────────────────────────────────────
    print("Step 1: データロード + signal生成...")
    signal_df, jp_close, jp_open, jp_oc, jp_cc, us_cc = _load_or_generate_signals()
    print(f"  signals: {len(signal_df)} dates ({signal_df.index[0].date()} 〜 {signal_df.index[-1].date()})")

    # ── 2. 全期間計算 ─────────────────────────────────────────────────────────
    print("Step 2: 全期間 戦略リターン計算...")
    strat_rows = compute_detailed_strategy_returns(signal_df, jp_close, jp_open, jp_oc, jp_cc, strategies)

    print("Step 3: JP特徴量 / Signal特徴量 / Regime計算...")
    jp_feat_df  = compute_jp_daily_features(signal_df, jp_close, jp_open, jp_oc, jp_cc)
    sig_feat_df = compute_signal_daily_features(signal_df)
    regime_df   = build_regime_frame(jp_cc, signal_df)

    # ── 3. 期間リスト構築 ─────────────────────────────────────────────────────
    all_periods: list[dict[str, str]] = []
    if not no_trailing:
        for tp in TRAILING_PERIODS:
            s, e = _resolve_period(tp["label"], tp["days"], signal_df)
            all_periods.append({"label": tp["label"], "start": s, "end": e})
    for up in user_periods:
        all_periods.append({"label": up["label"], "start": up["start"], "end": up["end"]})

    # ── 4. 各期間の集計 ──────────────────────────────────────────────────────
    print(f"Step 4: {len(all_periods)} 期間 × {len(strategies)} 戦略 の集計...")
    all_daily:   list[pd.DataFrame] = []
    all_monthly: list[pd.DataFrame] = []
    all_yearly:  list[pd.DataFrame] = []
    all_summary: list[pd.DataFrame] = []

    for p in all_periods:
        print(f"  period={p['label']}  {p['start']} 〜 {p['end']}")
        d = build_period_daily(strat_rows, sig_feat_df, jp_feat_df, regime_df,
                               strategies, p["label"], p["start"], p["end"])
        if d.empty:
            print(f"    → no data, skip")
            continue
        all_daily.append(d)

        mo = aggregate_monthly(d)
        yr = aggregate_yearly(d)
        sm = build_period_summary(d, p["label"], p["start"], p["end"], strategies)
        all_monthly.append(mo)
        all_yearly.append(yr)
        all_summary.append(sm)

    if not all_daily:
        raise RuntimeError("有効な期間データが1件もありません。")

    daily_df   = pd.concat(all_daily,   ignore_index=True)
    monthly_df = pd.concat(all_monthly, ignore_index=True)
    yearly_df  = pd.concat(all_yearly,  ignore_index=True)
    summary_df = pd.concat(all_summary, ignore_index=True)
    baseline_df = build_baseline_comparison(summary_df)

    # ── 5. ファイル出力 ───────────────────────────────────────────────────────
    output_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}

    def _save(df: pd.DataFrame, name: str) -> None:
        p = output_dir / name
        df.to_csv(p, index=False, encoding="utf-8-sig")
        files[name] = str(p)
        print(f"  wrote: {p}  ({len(df)} rows)")

    print("Step 5: CSV出力...")
    _save(daily_df,   "daily_strategy_metrics.csv")
    _save(monthly_df, "monthly_strategy_metrics.csv")
    _save(yearly_df,  "yearly_strategy_metrics.csv")
    _save(summary_df, "period_strategy_summary.csv")
    _save(baseline_df,"period_strategy_vs_baseline.csv")

    print("Step 6: 期間別個別ファイル出力...")
    per_period_dir = output_dir / "per_period"
    per_period_dir.mkdir(parents=True, exist_ok=True)
    for p in all_periods:
        plabel = p["label"]
        pp_daily   = daily_df[daily_df["period_label"] == plabel]
        if pp_daily.empty:
            continue
        pp_monthly  = monthly_df[monthly_df["period_label"] == plabel]
        pp_yearly   = yearly_df[yearly_df["period_label"] == plabel]
        pp_summary  = summary_df[summary_df["period_label"] == plabel]
        pp_baseline = baseline_df[baseline_df["period_label"] == plabel] if not baseline_df.empty else pd.DataFrame()
        pdir = per_period_dir / plabel
        pdir.mkdir(exist_ok=True)
        for df_pp, fname in [
            (pp_daily,    "daily.csv"),
            (pp_monthly,  "monthly.csv"),
            (pp_yearly,   "yearly.csv"),
            (pp_summary,  "summary.csv"),
            (pp_baseline, "vs_baseline.csv"),
        ]:
            fpath = pdir / fname
            df_pp.to_csv(fpath, index=False, encoding="utf-8-sig")
            files[f"per_period/{plabel}/{fname}"] = str(fpath)
        print(f"  {plabel}: {len(pp_daily)} daily rows")

    print("Step 7: Markdownレポート出力...")
    md_name = f"period_quant_output_{today.replace('-','')}.md"
    md_path = output_dir / md_name
    md = build_markdown_report(today, all_periods, summary_df, baseline_df, monthly_df, yearly_df)
    md_path.write_text(md, encoding="utf-8")
    files[md_name] = str(md_path)
    print(f"  wrote: {md_path}")

    # ── 6. サマリ ─────────────────────────────────────────────────────────────
    result = {
        "status":           "ok",
        "output_dir":       str(output_dir),
        "files":            files,
        "created_at":       today,
        "n_periods":        len(all_periods),
        "n_strategies":     len(strategies),
        "n_daily_rows":     len(daily_df),
        "n_monthly_rows":   len(monthly_df),
        "n_yearly_rows":    len(yearly_df),
        "n_summary_rows":   len(summary_df),
        "n_baseline_rows":  len(baseline_df),
        "has_missing":      bool((daily_df == NA).any().any()),
        "periods":          all_periods,
        "strategies":       list(strategies.keys()),
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--periods", type=str, default="[]",
                        help='JSON list: [{"label":"p01","start":"2026-05-01","end":"2026-06-15"}]')
    parser.add_argument("--output-dir", type=str, default="outputs/period_quant/default")
    parser.add_argument("--include-optional", action="store_true")
    parser.add_argument("--no-trailing", action="store_true",
                        help="自動付加のtrailing期間をスキップ（固定比較窓を明示指定した場合に使う）")
    args = parser.parse_args()

    try:
        user_periods = json.loads(args.periods)
    except json.JSONDecodeError as e:
        print(json.dumps({"status": "error", "error": f"JSON parse error: {e}"}))
        sys.exit(1)

    try:
        result = run(
            user_periods=user_periods,
            output_dir=Path(args.output_dir),
            include_optional=args.include_optional,
            no_trailing=args.no_trailing,
        )
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}))
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
