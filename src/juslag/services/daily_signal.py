from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from juslag.cache import PriceCache
from juslag.config import AppConfig, JP_CYCLICAL, JP_TICKERS, US_CYCLICAL, US_TICKERS
from juslag.data_loader import build_joint_cc, compute_returns, fetch_data
from juslag.prior import build_prior_eigenvectors, build_prior_exposure
from juslag.regime import build_regime_frame, snapshot_from_regime_frame
from juslag.signal import (
    DailySignalResult,
    apply_strategy_decision,
    append_daily_signal_log_csv,
    build_daily_signal_log_entry,
    classify_no_trade,
    compute_execution_target_jp_date,
    evaluate_daily_tradeability,
    generate_signals,
    resolve_thresholds,
    _build_candidate_signal_stats,
)
from juslag.strategies import StrategyContext, get_rule, list_rules

from juslag.services.data_status import build_data_status

_JST = ZoneInfo("Asia/Tokyo")
DEFAULT_ACTIVE_RULE_ID = "rule_406_no_flip"


def build_daily_execution_checks(
    data_quality: dict[str, object],
    freshness: dict[str, object],
    execution_plan: dict[str, object],
    regime_snapshot: dict[str, object] | None = None,
) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    latest_us = freshness.get("latest_us_date")
    latest_jp = freshness.get("latest_jp_date")
    freshness_ok = bool(freshness.get("freshness_ok"))
    checks.append(
        {
            "level": "ok" if freshness_ok else "warn",
            "message": f"データ新鮮度: {'OK' if freshness_ok else 'Warning'} (US最新={latest_us}, JP最新={latest_jp})",
        }
    )
    checks.append(
        {
            "level": "ok" if data_quality.get("fill_policy") == "strict" else "warn",
            "message": f"欠損処理: {data_quality.get('fill_policy')} / 補完セル数={data_quality.get('filled_cells', 0)}",
        }
    )
    n_long = execution_plan.get("n_long", 0)
    n_short = execution_plan.get("n_short", 0)
    cand_long = execution_plan.get("candidate_long_count", n_long)
    cand_short = execution_plan.get("candidate_short_count", n_short)
    min_long = execution_plan.get("min_long_signal", 0.0)
    max_short = execution_plan.get("max_short_signal", 0.0)
    checks.append(
        {
            "level": "ok",
            "message": f"LONG/SHORT 件数: {n_long} / {n_short}（quantile候補: {cand_long} / {cand_short}）",
        }
    )
    checks.append(
        {
            "level": "ok",
            "message": f"signal閾値: LONG>={min_long}, SHORT<={max_short}",
        }
    )
    checks.append(
        {
            "level": "warn" if execution_plan.get("n_short", 0) else "ok",
            "message": "SHORT には制度信用または貸株対応が必要",
        }
    )
    checks.append(
        {
            "level": "ok",
            "message": f"価格基準: {data_quality.get('price_mode')}（寄付き成行 / 引け成行 前提）",
        }
    )
    if regime_snapshot and regime_snapshot.get("regime_warning"):
        checks.append(
            {
                "level": "warn",
                "message": (
                    f"局面注意: {regime_snapshot.get('trend_regime')} × {regime_snapshot.get('vol_regime')}"
                    "（現行方向の信頼性低下に注意）"
                ),
            }
        )
    return checks


def build_order_json_payload(
    long_plan: list[dict],
    short_plan: list[dict],
) -> dict:
    """execution_plan の long/short 行から発注用JSONペイロード（canonical schema）を組み立てる。"""
    orders: list[dict] = []
    for row in long_plan:
        lots = row.get("normalized_lots") or 1
        orders.append({
            "stock_code": row["ticker"].replace(".T", ""),
            "order_kind": "genbutsu_buy",
            "quantity": lots,
            "nariyuki_condition": "寄成",
            "sor_enabled": False,
            "note": f"LONG / {row['sector']} / {lots}口",
        })
    for row in short_plan:
        lots = row.get("normalized_lots") or 1
        orders.append({
            "stock_code": row["ticker"].replace(".T", ""),
            "order_kind": "shinyo_sell",
            "quantity": lots,
            "payment_limit": "day",
            "nariyuki_condition": "寄成",
            "sor_enabled": False,
            "note": f"SHORT / {row['sector']} / {lots}口",
        })
    return {
        "common": {
            "market": "TKY",
            "price_type": "market",
            "validity": "this_day",
            "skip_estimate": True,
            "trade_password": "",
        },
        "orders": orders,
    }


def pick_overnight_gap(
    overnight_gap_df: pd.DataFrame,
    execution_target_jp_date: "pd.Timestamp | None",
) -> "pd.Series":
    """overnight_gap_df から適切な行を選ぶ。

    execution_target_jp_date が index にある場合はその行（JP執行日の寄りgap）を返す。
    ない場合は iloc[-1]（最新行）にフォールバックする。
    """
    if overnight_gap_df.empty:
        return pd.Series(dtype=float)
    if execution_target_jp_date is not None and execution_target_jp_date in overnight_gap_df.index:
        return overnight_gap_df.loc[execution_target_jp_date]
    return overnight_gap_df.iloc[-1]


def build_daily_signal_from_signal_df(
    signal_df: pd.DataFrame,
    jp_tickers_map: dict[str, str],
    q: float,
    min_long_signal: float,
    max_short_signal: float,
    vol_regime: str | None = None,
    adaptive_threshold: bool = False,
    regime_warning: bool = False,
) -> DailySignalResult:
    if signal_df.empty:
        return DailySignalResult(table=pd.DataFrame(columns=["sector", "signal", "position"]), signal_reference_us_date=pd.NaT, execution_target_jp_date=None)
    reference_date = signal_df.index[-1]
    latest = signal_df.iloc[-1]
    result = pd.DataFrame({
        "ticker": latest.index.tolist(),
        "sector": [jp_tickers_map.get(t, t) for t in latest.index],
        "signal": latest.values,
    }).set_index("ticker")
    eff_long_th, eff_short_th = resolve_thresholds(vol_regime, min_long_signal, max_short_signal, adaptive_threshold)
    lo = result["signal"].quantile(q)
    hi = result["signal"].quantile(1.0 - q)
    quantile_long_mask = result["signal"] >= hi
    quantile_short_mask = result["signal"] <= lo
    long_mask = quantile_long_mask & (result["signal"] >= eff_long_th)
    short_mask = quantile_short_mask & (result["signal"] <= eff_short_th)
    result["position"] = "neutral"
    result.loc[long_mask, "position"] = "LONG"
    result.loc[short_mask, "position"] = "SHORT"
    exec_date = compute_execution_target_jp_date(reference_date)
    source = "jpx_calendar" if exec_date is not None else "unavailable"
    stats = _build_candidate_signal_stats(
        result["signal"], quantile_long_mask, quantile_short_mask,
        eff_long_th, eff_short_th, jp_tickers_map,
    )
    adopted_long_count = int(long_mask.sum())
    adopted_short_count = int(short_mask.sum())
    adopted_long_sig = result.loc[long_mask, "signal"]
    adopted_short_sig = result.loc[short_mask, "signal"]
    adopted_signal_strength = round(float(adopted_long_sig.mean() - adopted_short_sig.mean()), 6) if not adopted_long_sig.empty and not adopted_short_sig.empty else 0.0
    tg_long = stats.get("long_threshold_gap_max")
    tg_short = stats.get("short_threshold_gap_max")
    no_trade = classify_no_trade(
        adopted_long_count, adopted_short_count, tg_long, tg_short,
        regime_warning=regime_warning,
    )
    return DailySignalResult(
        table=result.sort_values("signal", ascending=False),
        signal_reference_us_date=reference_date,
        execution_target_jp_date=exec_date,
        execution_target_jp_date_source=source,
        candidate_long_count=int(quantile_long_mask.sum()),
        candidate_short_count=int(quantile_short_mask.sum()),
        adopted_long_count=adopted_long_count,
        adopted_short_count=adopted_short_count,
        excluded_long=[{"ticker": t, "sector": str(result.loc[t, "sector"]), "signal": round(float(result.loc[t, "signal"]), 6)} for t in result.index[quantile_long_mask & ~long_mask]],
        excluded_short=[{"ticker": t, "sector": str(result.loc[t, "sector"]), "signal": round(float(result.loc[t, "signal"]), 6)} for t in result.index[quantile_short_mask & ~short_mask]],
        threshold_long_used=eff_long_th,
        threshold_short_used=eff_short_th,
        candidate_signal_stats=stats,
        candidate_signal_strength=float(stats.get("candidate_signal_strength") or 0.0),
        adopted_signal_strength=adopted_signal_strength,
        threshold_gap_long_max=tg_long,
        threshold_gap_short_max=tg_short,
        no_trade_classification=no_trade,
    )


def build_freshness(
    cache: PriceCache,
    us_tickers: list[str],
    jp_tickers: list[str],
    reference_date: str | None,
    price_mode: str,
) -> dict[str, object]:
    us_rep = cache.freshness_report(us_tickers, required_latest_date=reference_date, price_mode=price_mode)
    jp_rep = cache.freshness_report(jp_tickers, required_latest_date=reference_date, price_mode=price_mode)
    return {
        "price_mode": price_mode,
        "freshness_ok": bool(us_rep["freshness_ok"] and jp_rep["freshness_ok"]),
        "latest_us_date": us_rep["latest_date"],
        "latest_jp_date": jp_rep["latest_date"],
        "stale_tickers": sorted(set((us_rep.get("stale_tickers") or []) + (jp_rep.get("stale_tickers") or []))),
        "missing_tickers": sorted(set((us_rep.get("missing_tickers") or []) + (jp_rep.get("missing_tickers") or []))),
    }


def run_daily_signal_service(
    cfg: AppConfig,
    cache: PriceCache,
    *,
    operation_mode: str | None = None,
    window_l: int | None = None,
    k_factors: int | None = None,
    lambda_reg: float | None = None,
    quantile_q: float | None = None,
    min_long_signal: float | None = None,
    max_short_signal: float | None = None,
    log_path: Path | None = None,
    analysis_status: dict | None = None,
    now_jst: datetime | None = None,
    active_rule_id: str | None = None,
    generate_signals_fn=generate_signals,
    get_rule_fn=get_rule,
    pick_overnight_gap_fn=pick_overnight_gap,
) -> dict[str, object]:
    now_jst = now_jst if now_jst is not None else datetime.now(_JST)
    eff_window_l = window_l if window_l is not None else cfg.strategy.window_l
    eff_k = k_factors if k_factors is not None else cfg.strategy.k_factors
    eff_lambda = lambda_reg if lambda_reg is not None else cfg.strategy.lambda_reg
    eff_q = quantile_q if quantile_q is not None else cfg.strategy.quantile_q
    eff_min_long = min_long_signal if min_long_signal is not None else cfg.strategy.min_long_signal
    eff_max_short = max_short_signal if max_short_signal is not None else cfg.strategy.max_short_signal
    sample_end = (now_jst.date() + timedelta(days=1)).isoformat()

    us_close, jp_close, jp_open = fetch_data(
        list(US_TICKERS.keys()),
        list(JP_TICKERS.keys()),
        cfg.daily.sample_start,
        sample_end,
        price_mode="raw",
    )
    us_cc, jp_oc_daily, jp_cc = compute_returns(us_close, jp_close, jp_open)

    us_tickers = us_close.columns.tolist()
    jp_tickers = jp_close.columns.tolist()
    v0 = build_prior_eigenvectors(us_tickers, jp_tickers, US_CYCLICAL, JP_CYCLICAL)

    joint_cc, quality = build_joint_cc(
        us_cc,
        jp_cc,
        fill_policy="strict",
        sample_start=cfg.daily.sample_start,
        sample_end=sample_end,
        price_mode="raw",
    )
    pretrain_data = joint_cc.loc[: cfg.daily.pretrain_end]
    c0 = build_prior_exposure(pretrain_data, v0)

    signal_df = generate_signals_fn(
        us_cc,
        jp_cc,
        c0,
        l=eff_window_l,
        k=eff_k,
        lam=eff_lambda,
    )
    # Compute regime first so vol_regime can inform adaptive threshold.
    regime_df = build_regime_frame(jp_cc, signal_df)
    _ref_date_pre = signal_df.index[-1] if not signal_df.empty else pd.NaT
    regime_snapshot = snapshot_from_regime_frame(regime_df, _ref_date_pre)
    operation_mode = operation_mode or cfg.strategy.operation_mode

    daily_signal_result = build_daily_signal_from_signal_df(
        signal_df,
        JP_TICKERS,
        eff_q,
        eff_min_long,
        eff_max_short,
        vol_regime=regime_snapshot.vol_regime,
        adaptive_threshold=cfg.strategy.adaptive_threshold,
        regime_warning=bool(regime_snapshot.regime_warning),
    )
    reference_date = daily_signal_result.signal_reference_us_date
    execution_target_jp_date = daily_signal_result.execution_target_jp_date
    execution_target_jp_date_source = daily_signal_result.execution_target_jp_date_source
    if operation_mode not in {"production", "development"}:
        raise ValueError("operation_mode must be production or development")

    # overnight gap = (JP執行日寄り - 前日JP終) / 前日JP終 = 本物の寄りgap
    overnight_gap_df = jp_open / jp_close.shift(1) - 1.0
    overnight_gap_latest = pick_overnight_gap_fn(overnight_gap_df, execution_target_jp_date)

    # StrategyContext 用 gap 値を overnight_gap から計算
    # open_gap: 全銘柄平均
    _open_gap: float | None = float(overnight_gap_latest.mean()) if not overnight_gap_latest.empty else None
    # LONG/SHORT 候補銘柄（quantile候補 = adopted + excluded）のgap平均
    _long_candidate_tickers = (
        [x["ticker"] for x in (daily_signal_result.excluded_long or [])]
        + daily_signal_result.table.index[daily_signal_result.table["position"] == "LONG"].tolist()
    )
    _short_candidate_tickers = (
        [x["ticker"] for x in (daily_signal_result.excluded_short or [])]
        + daily_signal_result.table.index[daily_signal_result.table["position"] == "SHORT"].tolist()
    )
    _long_gaps = overnight_gap_latest.reindex(_long_candidate_tickers).dropna()
    _short_gaps = overnight_gap_latest.reindex(_short_candidate_tickers).dropna()
    _long_gap: float | None = float(_long_gaps.mean()) if not _long_gaps.empty else None
    _short_gap: float | None = float(_short_gaps.mean()) if not _short_gaps.empty else None

    _signal_date_str = str(reference_date.date()) if pd.notna(reference_date) else now_jst.date().isoformat()
    _strategy_ctx = StrategyContext(
        signal_date=_signal_date_str,
        candidate_signal_strength=daily_signal_result.candidate_signal_strength if daily_signal_result.candidate_signal_strength != 0.0 else None,
        open_gap=_open_gap,
        long_gap=_long_gap,
        short_gap=_short_gap,
        trend_regime=regime_snapshot.trend_regime,  # type: ignore[arg-type]
        vol_regime=regime_snapshot.vol_regime,  # type: ignore[arg-type]
        rotation_regime=regime_snapshot.rotation_regime,  # type: ignore[arg-type]
    )
    _active_rule_id = active_rule_id or DEFAULT_ACTIVE_RULE_ID
    try:
        _active_rule = get_rule_fn(_active_rule_id)
    except ValueError:
        _active_rule = get_rule_fn("rule_406")
    _strategy_decision = _active_rule.decide(_strategy_ctx)

    # shadow decisions: 全ルールをアクティブルール以外で評価（記録・比較用）
    _shadow_decisions: dict[str, object] = {}
    for _shadow_rule in list_rules():
        if _shadow_rule.rule_id == _active_rule_id:
            continue
        try:
            _shadow_dec = _shadow_rule.decide(_strategy_ctx)
            _shadow_decisions[_shadow_rule.rule_id] = _shadow_dec.to_dict()
        except Exception:  # noqa: BLE001
            pass

    # apply_strategy_decision() 前の状態を退避（分類判定・API返却に使用）
    pre_rule_adopted_long_count = daily_signal_result.adopted_long_count
    pre_rule_adopted_short_count = daily_signal_result.adopted_short_count
    pre_rule_candidate_long_count = daily_signal_result.candidate_long_count
    pre_rule_candidate_short_count = daily_signal_result.candidate_short_count
    pre_rule_no_trade_classification = daily_signal_result.no_trade_classification
    pre_rule_has_both_adopted_candidates = (
        pre_rule_adopted_long_count >= 1
        and pre_rule_adopted_short_count >= 1
    )

    # StrategyDecision を実際のポジション生成に適用
    daily_signal_result = apply_strategy_decision(
        daily_signal_result,
        selected_strategy=_strategy_decision.selected_strategy,
        overnight_gap=overnight_gap_latest,
    )

    today_signal = daily_signal_result.table
    daily_df = today_signal.reset_index().rename(columns={"index": "Ticker"})

    long_rows = today_signal[today_signal["position"] == "LONG"]
    short_rows = today_signal[today_signal["position"] == "SHORT"]
    n_long = len(long_rows)
    n_short = len(short_rows)

    # 最新終値（最低購入金額の計算用）
    latest_prices = jp_close.iloc[-1] if not jp_close.empty else pd.Series(dtype=float)
    # TOPIX-17 NEXT FUNDS ETF: 最低売買単位 = 10口
    _MIN_LOT = 10

    def _plan_entry(t: str, row: object, n: int) -> dict[str, object]:
        price = latest_prices.get(t)
        min_purchase = round(float(price) * _MIN_LOT) if price is not None and not pd.isna(price) else None
        return {
            "ticker": t,
            "sector": row["sector"],
            "weight": round(1.0 / n * 100, 1),
            "latest_price_jpy": round(float(price)) if price is not None and not pd.isna(price) else None,
            "min_lot": _MIN_LOT,
            "min_purchase_jpy": min_purchase,
        }

    long_plan = [_plan_entry(t, row, n_long) for t, row in long_rows.iterrows()] if n_long > 0 else []
    short_plan = [_plan_entry(t, row, n_short) for t, row in short_rows.iterrows()] if n_short > 0 else []

    # 1番高いセクターの最低購入金額(10口)に金額を合わせた口数を計算
    all_entries = long_plan + short_plan
    valid_prices = [e["latest_price_jpy"] for e in all_entries if e["latest_price_jpy"] is not None]
    if valid_prices:
        max_lot_price = max(valid_prices)
        for entry in all_entries:
            price = entry["latest_price_jpy"]
            if price is not None and price > 0:
                norm_lots = max(1, round(max_lot_price / price))
                entry["normalized_lots"] = norm_lots
                entry["normalized_purchase_jpy"] = round(norm_lots * price)
            else:
                entry["normalized_lots"] = None
                entry["normalized_purchase_jpy"] = None
    quality["reference_date"] = str(reference_date)
    quality["effective_window_days"] = int(min(eff_window_l, len(joint_cc)))
    freshness = build_freshness(
        cache,
        list(US_TICKERS.keys()),
        list(JP_TICKERS.keys()),
        str(reference_date) if pd.notna(reference_date) else None,
        "raw",
    )
    cache_summary = cache.summary(
        list(US_TICKERS.keys()),
        list(JP_TICKERS.keys()),
        required_latest_date=str(reference_date) if pd.notna(reference_date) else None,
        price_mode="raw",
    )
    quality.update(freshness)
    execution_plan = {
        "long": long_plan,
        "short": short_plan,
        "n_long": n_long,
        "n_short": n_short,
        "candidate_long_count": daily_signal_result.candidate_long_count,
        "candidate_short_count": daily_signal_result.candidate_short_count,
        "adopted_long_count": daily_signal_result.adopted_long_count,
        "adopted_short_count": daily_signal_result.adopted_short_count,
        "excluded_long": daily_signal_result.excluded_long or [],
        "excluded_short": daily_signal_result.excluded_short or [],
        "min_long_signal": eff_min_long,
        "max_short_signal": eff_max_short,
        "threshold_long_used": daily_signal_result.threshold_long_used,
        "threshold_short_used": daily_signal_result.threshold_short_used,
        "adaptive_threshold_active": cfg.strategy.adaptive_threshold,
    }
    execution_checks = build_daily_execution_checks(
        quality,
        freshness,
        execution_plan,
        regime_snapshot={
            "trend_regime": regime_snapshot.trend_regime,
            "vol_regime": regime_snapshot.vol_regime,
            "regime_warning": regime_snapshot.regime_warning,
        },
    )
    if analysis_status is None:
        analysis_status = build_data_status(cache, cfg)
    tradeability = evaluate_daily_tradeability(
        today_signal,
        quality,
        freshness,
        cache_summary,
        min_signal_spread=cfg.strategy.min_signal_spread,
        execution_target_jp_date=execution_target_jp_date,
        execution_target_jp_date_source=execution_target_jp_date_source,
        operation_mode=operation_mode,
        candidate_long_count=daily_signal_result.candidate_long_count,
        candidate_short_count=daily_signal_result.candidate_short_count,
        adopted_long_count=daily_signal_result.adopted_long_count,
        adopted_short_count=daily_signal_result.adopted_short_count,
        min_adopted_long_count=cfg.strategy.min_adopted_long_count,
        min_adopted_short_count=cfg.strategy.min_adopted_short_count,
    )
    # strategy_rule の skip 決定は最優先ブロック理由として上書き
    _strategy_rule_skipped = _strategy_decision.action == "skip"
    if _strategy_rule_skipped:
        tradeability["tradeable"] = False
        tradeability["trade_block_reason"] = "strategy_rule_skip"
    # no_trade_classification の優先順位（apply前の pre_rule 値を使用）:
    #   data_quality/freshness/execution_block > strategy_rule_skip
    #   > no_long/short_candidates > threshold_near_miss > no_signal
    if _strategy_rule_skipped:
        _effective_no_trade = (
            "strategy_rule_skip_with_candidates"
            if pre_rule_has_both_adopted_candidates
            else "strategy_rule_skip"
        )
    else:
        _effective_no_trade = pre_rule_no_trade_classification
    if log_path is not None:
        append_daily_signal_log_csv(
            log_path,
            build_daily_signal_log_entry(
                signal_reference_us_date=str(reference_date) if pd.notna(reference_date) else None,
                execution_target_jp_date=str(execution_target_jp_date.date()) if execution_target_jp_date is not None else None,
                execution_target_jp_date_source=execution_target_jp_date_source,
                operation_mode=operation_mode,
                trade_signal_strength=tradeability["trade_signal_strength"],
                tradeable=tradeability["tradeable"],
                trade_block_reason=tradeability["trade_block_reason"],
                min_signal_spread_used=cfg.strategy.min_signal_spread,
                min_long_signal_used=eff_min_long,
                max_short_signal_used=eff_max_short,
                min_adopted_long_count_used=cfg.strategy.min_adopted_long_count,
                min_adopted_short_count_used=cfg.strategy.min_adopted_short_count,
                candidate_long_count=daily_signal_result.candidate_long_count,
                candidate_short_count=daily_signal_result.candidate_short_count,
                adopted_long_count=daily_signal_result.adopted_long_count,
                adopted_short_count=daily_signal_result.adopted_short_count,
                freshness_ok=bool(freshness.get("freshness_ok")),
                latest_dates_aligned=bool(cache_summary.get("latest_dates_aligned")),
                usable_us_tickers=int(quality.get("usable_us_tickers") or 0),
                usable_jp_tickers=int(quality.get("usable_jp_tickers") or 0),
                long_tickers=[x["ticker"] for x in long_plan],
                short_tickers=[x["ticker"] for x in short_plan],
                trend_regime=regime_snapshot.trend_regime,
                vol_regime=regime_snapshot.vol_regime,
                rotation_regime=regime_snapshot.rotation_regime,
                regime_warning=regime_snapshot.regime_warning,
                regime_warning_reason=regime_snapshot.regime_warning_reason,
                candidate_signal_strength=daily_signal_result.candidate_signal_strength,
                adopted_signal_strength=daily_signal_result.adopted_signal_strength,
                threshold_gap_long_max=daily_signal_result.threshold_gap_long_max,
                threshold_gap_short_max=daily_signal_result.threshold_gap_short_max,
                no_trade_classification=daily_signal_result.no_trade_classification,
            ),
        )

    return {
        "reference_date": str(reference_date),
        "signal_reference_us_date": str(reference_date) if pd.notna(reference_date) else None,
        "execution_target_jp_date": str(execution_target_jp_date.date()) if execution_target_jp_date is not None else None,
        "execution_target_jp_date_source": execution_target_jp_date_source,
        "operation_mode": operation_mode,
        "rows": daily_df.to_dict(orient="records"),
        "execution_plan": execution_plan,
        "data_quality": quality,
        "freshness": freshness,
        "cache_summary": cache_summary,
        "execution_checks": execution_checks,
        "trade_signal_strength": tradeability["trade_signal_strength"],
        "tradeable": tradeability["tradeable"],
        "trade_block_reason": tradeability["trade_block_reason"],
        "calendar_warning": tradeability["calendar_warning"],
        "min_signal_spread_used": cfg.strategy.min_signal_spread,
        "min_long_signal": cfg.strategy.min_long_signal,
        "max_short_signal": cfg.strategy.max_short_signal,
        "min_adopted_long_count": cfg.strategy.min_adopted_long_count,
        "min_adopted_short_count": cfg.strategy.min_adopted_short_count,
        "candidate_long_count": pre_rule_candidate_long_count,
        "candidate_short_count": pre_rule_candidate_short_count,
        "adopted_long_count": daily_signal_result.adopted_long_count,
        "adopted_short_count": daily_signal_result.adopted_short_count,
        "pre_rule_adopted_long_count": pre_rule_adopted_long_count,
        "pre_rule_adopted_short_count": pre_rule_adopted_short_count,
        "post_rule_adopted_long_count": daily_signal_result.adopted_long_count,
        "post_rule_adopted_short_count": daily_signal_result.adopted_short_count,
        "excluded_long": daily_signal_result.excluded_long or [],
        "excluded_short": daily_signal_result.excluded_short or [],
        "candidate_signal_stats": daily_signal_result.candidate_signal_stats or {},
        "threshold_long_used": daily_signal_result.threshold_long_used,
        "threshold_short_used": daily_signal_result.threshold_short_used,
        "adaptive_threshold_active": cfg.strategy.adaptive_threshold,
        "candidate_signal_strength": daily_signal_result.candidate_signal_strength,
        "adopted_signal_strength": daily_signal_result.adopted_signal_strength,
        "threshold_gap_long_max": daily_signal_result.threshold_gap_long_max,
        "threshold_gap_short_max": daily_signal_result.threshold_gap_short_max,
        "no_trade_classification": _effective_no_trade,
        "signal_no_trade_classification": pre_rule_no_trade_classification,
        "strategy_rule_skip_has_candidates": pre_rule_has_both_adopted_candidates if _strategy_rule_skipped else False,
        "trend_regime": regime_snapshot.trend_regime,
        "vol_regime": regime_snapshot.vol_regime,
        "rotation_regime": regime_snapshot.rotation_regime,
        "regime_warning": regime_snapshot.regime_warning,
        "regime_warning_reason": regime_snapshot.regime_warning_reason,
        "regime_warning_message": regime_snapshot.regime_warning_message,
        "actions_data_available": analysis_status.get("corporate_actions", {}).get("available"),
        "adjusted_series_verified": analysis_status.get("adjusted_series_verified"),
        "adjusted_series_warning": analysis_status.get("adjusted_series_warning"),
        "adjusted_series_verification_reason": analysis_status.get("adjusted_series_verification_reason"),
        "analysis_readiness": analysis_status.get("analysis_readiness"),
        "factor_data_available": analysis_status.get("factor_data", {}).get("available"),
        "strategy_decision": _strategy_decision.to_dict(),
        "selected_strategy": daily_signal_result.selected_strategy,
        "strategy_context": {
            "open_gap": _strategy_ctx.open_gap,
            "long_gap": _strategy_ctx.long_gap,
            "short_gap": _strategy_ctx.short_gap,
            "candidate_signal_strength": _strategy_ctx.candidate_signal_strength,
            "trend_regime": _strategy_ctx.trend_regime,
            "vol_regime": _strategy_ctx.vol_regime,
            "rotation_regime": _strategy_ctx.rotation_regime,
        },
        "shadow_decisions": _shadow_decisions,
    }
