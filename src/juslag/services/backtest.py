from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, Field

from juslag.cache import PriceCache
from juslag.config import AppConfig, ExecutionCostConfig, JP_CYCLICAL, JP_TICKERS, TaxConfig, US_CYCLICAL, US_TICKERS
from juslag.data_loader import build_joint_cc, compute_returns, fetch_data
from juslag.judge import JudgeInput, judge_backtest
from juslag.metrics import apply_tax_model, compute_performance
from juslag.portfolio import build_portfolio, build_portfolio_returns_detail, build_portfolio_with_strategy_rule
from juslag.prior import build_prior_eigenvectors, build_prior_exposure
from juslag.regime import build_regime_frame
from juslag.signal import generate_signals
from juslag.strategies import get_rule

from juslag.services.daily_signal import build_freshness
from juslag.services.data_status import build_data_status


class BacktestParams(BaseModel):
    _cfg = AppConfig()
    sample_start: str = Field(default=_cfg.paper_like.sample_start)
    sample_end: str = Field(default=_cfg.paper_like.sample_end or "")
    pretrain_end: str = Field(default=_cfg.paper_like.pretrain_end)
    window_l: int = Field(default=_cfg.strategy.window_l, ge=5, le=252)
    k_factors: int = Field(default=_cfg.strategy.k_factors, ge=1, le=10)
    lambda_reg: float = Field(default=_cfg.strategy.lambda_reg, ge=0.0, le=1.0)
    quantile_q: float = Field(default=_cfg.strategy.quantile_q, gt=0.0, lt=0.5)
    min_long_signal: float = Field(default=_cfg.strategy.min_long_signal)
    max_short_signal: float = Field(default=_cfg.strategy.max_short_signal)
    fill_policy: str = Field(default="strict")
    price_mode: str = Field(default="raw")
    commission_bps_per_side: float = Field(default=5.0, ge=0.0)
    slippage_bps_per_side: float = Field(default=5.0, ge=0.0)
    short_borrow_rate_annual: float = Field(default=0.015, ge=0.0)
    allow_short: bool = Field(default=True)
    short_constraint_mode: str = Field(default="ignore")
    unshortable_tickers: list[str] = Field(default_factory=list)
    tax_enabled: bool = Field(default=True)
    tax_rate: float = Field(default=0.20315, ge=0.0, le=1.0)
    tax_model: str = Field(default="annual_net")
    tax_loss_carryforward_years: int = Field(default=3, ge=0, le=10)
    strategy_rule_id: str | None = Field(default=None, description="メタ戦略ルールID（Noneの場合はルールなし）")


def compute_timeseries_payload(gross: pd.Series, net_pre_tax: pd.Series, net_after_tax: pd.Series) -> dict[str, list[float | str]]:
    gross_equity = (1.0 + gross.fillna(0.0)).cumprod()
    net_pre_tax_equity = (1.0 + net_pre_tax.fillna(0.0)).cumprod()
    net_after_tax_equity = (1.0 + net_after_tax.fillna(0.0)).cumprod()

    gross_drawdown = gross_equity / gross_equity.cummax() - 1.0
    net_after_tax_drawdown = net_after_tax_equity / net_after_tax_equity.cummax() - 1.0

    return {
        "dates": [d.strftime("%Y-%m-%d") for d in gross.index],
        "gross_equity": gross_equity.round(8).tolist(),
        "net_pre_tax_equity": net_pre_tax_equity.round(8).tolist(),
        "net_after_tax_equity": net_after_tax_equity.round(8).tolist(),
        "gross_drawdown": gross_drawdown.round(8).tolist(),
        "net_after_tax_drawdown": net_after_tax_drawdown.round(8).tolist(),
    }


def run_backtest_service(
    params: BacktestParams,
    cache: PriceCache,
    analysis_status: dict | None = None,
) -> dict[str, object]:
    us_close, jp_close, jp_open = fetch_data(
        list(US_TICKERS.keys()),
        list(JP_TICKERS.keys()),
        params.sample_start,
        params.sample_end,
        price_mode=params.price_mode,
    )
    us_cc, jp_oc, jp_cc = compute_returns(us_close, jp_close, jp_open)

    us_tickers = us_close.columns.tolist()
    jp_tickers = jp_close.columns.tolist()
    v0 = build_prior_eigenvectors(us_tickers, jp_tickers, US_CYCLICAL, JP_CYCLICAL)

    joint_cc, quality = build_joint_cc(
        us_cc,
        jp_cc,
        fill_policy=params.fill_policy,
        sample_start=params.sample_start,
        sample_end=params.sample_end,
        price_mode=params.price_mode,
    )
    pretrain_data = joint_cc.loc[: params.pretrain_end]
    c0 = build_prior_exposure(pretrain_data, v0)

    signal_sub = generate_signals(
        us_cc,
        jp_cc,
        c0,
        l=params.window_l,
        k=params.k_factors,
        lam=params.lambda_reg,
    )
    signal_plain = generate_signals(
        us_cc,
        jp_cc,
        c0,
        l=params.window_l,
        k=params.k_factors,
        lam=0.0,
    )
    signal_mom = jp_cc.rolling(params.window_l).mean().shift(1)

    eval_start = f"{int(params.pretrain_end[:4]) + 1}-01-01"

    # メタ戦略ルール適用バックテスト（事前計算: exec_cfg の前に変数のみ用意）
    meta_rule_ret: pd.Series | None = None
    meta_rule_name: str | None = None

    exec_cfg = ExecutionCostConfig(
        commission_bps_per_side=params.commission_bps_per_side,
        slippage_bps_per_side=params.slippage_bps_per_side,
        short_borrow_rate_annual=params.short_borrow_rate_annual,
        allow_short=params.allow_short,
        short_constraint_mode=params.short_constraint_mode,
        unshortable_tickers=tuple(params.unshortable_tickers),
    )
    tax_cfg = TaxConfig(
        enabled=params.tax_enabled,
        tax_rate=params.tax_rate,
        tax_model=params.tax_model,
        loss_carryforward_years=params.tax_loss_carryforward_years,
    )

    ret_sub_detail = build_portfolio_returns_detail(signal_sub[eval_start:], jp_oc[eval_start:], q=params.quantile_q, execution_costs=exec_cfg, min_long_signal=params.min_long_signal, max_short_signal=params.max_short_signal)
    ret_sub = ret_sub_detail["net_pre_tax_return"] if not ret_sub_detail.empty else pd.Series(dtype=float)
    tax_detail = apply_tax_model(ret_sub, tax_cfg)
    ret_sub_after_tax = tax_detail["net_after_tax_return"] if not tax_detail.empty else pd.Series(dtype=float)

    ret_plain = build_portfolio(signal_plain[eval_start:], jp_oc[eval_start:], q=params.quantile_q, execution_costs=exec_cfg)
    ret_mom = build_portfolio(signal_mom[eval_start:], jp_oc[eval_start:], q=params.quantile_q, execution_costs=exec_cfg)

    gross = ret_sub_detail["gross_return"] if not ret_sub_detail.empty else pd.Series(dtype=float)
    net_pre_tax = ret_sub
    net_after_tax = ret_sub_after_tax

    performance_sets = {
        "gross": [compute_performance(gross, "PCA SUB (Gross)")],
        "net_pre_tax": [compute_performance(net_pre_tax, "PCA SUB (Net Pre-Tax)")],
        "net_after_tax": [compute_performance(net_after_tax, "PCA SUB (Net After-Tax)")],
    }

    perf_df = pd.DataFrame(
        [
            compute_performance(ret_mom, "MOM (Momentum)"),
            compute_performance(ret_plain, "PCA PLAIN"),
            compute_performance(net_pre_tax, "PCA SUB"),
        ]
    )

    if params.strategy_rule_id:
        try:
            _meta_rule = get_rule(params.strategy_rule_id)
            overnight_gap_df = jp_open / jp_close.shift(1) - 1.0
            # regime_df を backtest でも構築
            _regime_df = build_regime_frame(jp_cc, signal_sub)
            ret_meta_detail = build_portfolio_with_strategy_rule(
                signal_sub[eval_start:],
                jp_oc[eval_start:],
                overnight_gap_df[eval_start:],
                _regime_df[eval_start:] if _regime_df is not None else None,
                _meta_rule,
                q=params.quantile_q,
                execution_costs=exec_cfg,
                min_long_signal=params.min_long_signal,
                max_short_signal=params.max_short_signal,
            )
            meta_rule_ret = ret_meta_detail["net_pre_tax_return"] if not ret_meta_detail.empty else pd.Series(dtype=float)
            meta_rule_name = f"PCA SUB + {params.strategy_rule_id}"
        except (ValueError, Exception):
            meta_rule_ret = None
            meta_rule_name = None

    if meta_rule_ret is not None and meta_rule_name:
        tax_meta = apply_tax_model(meta_rule_ret, tax_cfg)
        meta_after_tax = tax_meta["net_after_tax_return"] if not tax_meta.empty else pd.Series(dtype=float)
        performance_sets["meta_rule_net_pre_tax"] = [compute_performance(meta_rule_ret, meta_rule_name)]
        performance_sets["meta_rule_net_after_tax"] = [compute_performance(meta_after_tax, f"{meta_rule_name} (After-Tax)")]
        perf_df = pd.concat([
            perf_df,
            pd.DataFrame([
                compute_performance(meta_rule_ret, meta_rule_name),
                compute_performance(meta_after_tax, f"{meta_rule_name} (After-Tax)"),
            ]),
        ], ignore_index=True)

    cost_breakdown = {
        "commission_total": float(ret_sub_detail["commission_cost"].sum()) if not ret_sub_detail.empty else 0.0,
        "slippage_total": float(ret_sub_detail["slippage_cost"].sum()) if not ret_sub_detail.empty else 0.0,
        "borrow_total": float(ret_sub_detail["borrow_cost"].sum()) if not ret_sub_detail.empty else 0.0,
        "tax_total": float(tax_detail["tax_paid"].sum()) if not tax_detail.empty else 0.0,
    }

    timeseries = compute_timeseries_payload(gross, net_pre_tax, net_after_tax) if not ret_sub_detail.empty else {
        "dates": [],
        "gross_equity": [],
        "net_pre_tax_equity": [],
        "net_after_tax_equity": [],
        "gross_drawdown": [],
        "net_after_tax_drawdown": [],
    }

    freshness = build_freshness(
        cache,
        list(US_TICKERS.keys()),
        list(JP_TICKERS.keys()),
        joint_cc.index.max().date().isoformat() if not joint_cc.empty else None,
        params.price_mode,
    )
    cache_summary = cache.summary(
        list(US_TICKERS.keys()),
        list(JP_TICKERS.keys()),
        required_latest_date=joint_cc.index.max().date().isoformat() if not joint_cc.empty else None,
        price_mode=params.price_mode,
    )
    judge_result = judge_backtest(
        JudgeInput(
            strategy_name="PCA SUB",
            performance_sets=performance_sets,
            cost_breakdown=cost_breakdown,
            data_quality=quality,
            freshness=freshness,
            cache_summary=cache_summary,
        )
    )

    if analysis_status is None:
        try:
            analysis_status = build_data_status(cache, AppConfig.load())
        except Exception:
            analysis_status = None

    return {
        "params": params.model_dump(),
        "rows": perf_df.to_dict(orient="records"),
        "performance_sets": performance_sets,
        "timeseries": timeseries,
        "cost_breakdown": cost_breakdown,
        "eval_start": eval_start,
        "data_quality": quality,
        "freshness": freshness,
        "cache_summary": cache_summary,
        "judge": judge_result,
        "actions_data_available": analysis_status.get("corporate_actions", {}).get("available") if analysis_status else None,
        "adjusted_series_verified": analysis_status.get("adjusted_series_verified") if analysis_status else None,
        "adjusted_series_warning": analysis_status.get("adjusted_series_warning") if analysis_status else None,
        "adjusted_series_verification_reason": analysis_status.get("adjusted_series_verification_reason") if analysis_status else None,
        "strategy_rule_id": params.strategy_rule_id,
    }
