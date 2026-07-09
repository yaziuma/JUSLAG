from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

DEFAULT_APP_CONFIG_PATH = Path("config/app.yaml")

US_TICKERS: dict[str, str] = {
    "XLB": "Materials",
    "XLE": "Energy",
    "XLF": "Financials",
    "XLI": "Industrials",
    "XLK": "Information Technology",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLV": "Health Care",
    "XLY": "Consumer Discretionary",
    "XLC": "Communication Services",
    "XLRE": "Real Estate",
}

JP_TICKERS: dict[str, str] = {
    "1617.T": "食品",
    "1618.T": "エネルギー資源",
    "1619.T": "建設・資材",
    "1620.T": "素材・化学",
    "1621.T": "医薬品",
    "1622.T": "自動車・輸送機",
    "1623.T": "鉄鋼・非鉄",
    "1624.T": "機械",
    "1625.T": "電機・精密",
    "1626.T": "情報通信・サービスその他",
    "1627.T": "電力・ガス",
    "1628.T": "運輸・物流",
    "1629.T": "商社・卸売",
    "1630.T": "小売",
    "1631.T": "銀行",
    "1632.T": "金融（除く銀行）",
    "1633.T": "不動産",
}

US_CYCLICAL: dict[str, int] = {
    # 論文 Section 4.1 準拠: シクリカル=+1, ディフェンシブ=-1, 未ラベル=0
    "XLB": 1,    # Materials          - Cyclical
    "XLE": 1,    # Energy             - Cyclical
    "XLF": 1,    # Financials         - Cyclical
    "XLI": 0,    # Industrials        - 未ラベル
    "XLK": -1,   # Information Tech   - Defensive
    "XLP": -1,   # Consumer Staples   - Defensive
    "XLU": -1,   # Utilities          - Defensive
    "XLV": -1,   # Health Care        - Defensive
    "XLY": 0,    # Consumer Discret.  - 未ラベル
    "XLC": 0,    # Communication Svc  - 未ラベル
    "XLRE": 1,   # Real Estate        - Cyclical
}

JP_CYCLICAL: dict[str, int] = {
    # 論文 Section 4.1 準拠: シクリカル=+1, ディフェンシブ=-1, 未ラベル=0
    "1617.T": -1,  # 食品               - Defensive
    "1618.T": 1,   # エネルギー資源      - Cyclical
    "1619.T": 0,   # 建設・資材          - 未ラベル
    "1620.T": 0,   # 素材・化学          - 未ラベル
    "1621.T": -1,  # 医薬品             - Defensive
    "1622.T": 0,   # 自動車・輸送機       - 未ラベル
    "1623.T": 0,   # 鉄鋼・非鉄          - 未ラベル
    "1624.T": 0,   # 機械               - 未ラベル
    "1625.T": 1,   # 電機・精密          - Cyclical
    "1626.T": 0,   # 情報通信・サービス    - 未ラベル
    "1627.T": -1,  # 電力・ガス          - Defensive
    "1628.T": 0,   # 運輸・物流          - 未ラベル
    "1629.T": 1,   # 商社・卸売          - Cyclical
    "1630.T": -1,  # 小売               - Defensive
    "1631.T": 1,   # 銀行               - Cyclical
    "1632.T": 0,   # 金融（除く銀行）     - 未ラベル
    "1633.T": 0,   # 不動産             - 未ラベル
}


@dataclass(frozen=True)
class StrategyConfig:
    window_l: int = 60
    k_factors: int = 3
    lambda_reg: float = 0.9
    quantile_q: float = 0.3
    min_signal_spread: float = 0.0
    min_long_signal: float = 0.0
    max_short_signal: float = 0.0
    min_adopted_long_count: int = 1
    min_adopted_short_count: int = 1
    operation_mode: Literal["production", "development"] = "production"
    adaptive_threshold: bool = False


@dataclass(frozen=True)
class ModeConfig:
    name: str
    sample_start: str
    sample_end: str | None
    pretrain_end: str


@dataclass(frozen=True)
class ExecutionCostConfig:
    commission_bps_per_side: float = 5.0
    slippage_bps_per_side: float = 5.0
    short_borrow_rate_annual: float = 0.015
    allow_short: bool = True
    short_constraint_mode: str = "ignore"
    unshortable_tickers: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaxConfig:
    enabled: bool = True
    tax_rate: float = 0.20315
    tax_model: str = "annual_net"
    loss_carryforward_years: int = 3


@dataclass(frozen=True)
class AppConfig:
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    execution_costs: ExecutionCostConfig = field(default_factory=ExecutionCostConfig)
    tax: TaxConfig = field(default_factory=TaxConfig)
    paper_like: ModeConfig = field(
        default_factory=lambda: ModeConfig(
            name="paper_like",
            sample_start="2018-07-01",
            sample_end="2025-12-31",
            pretrain_end="2021-12-31",
        )
    )
    daily: ModeConfig = field(
        default_factory=lambda: ModeConfig(
            name="daily",
            sample_start="2018-07-01",
            sample_end=None,
            pretrain_end="2021-12-31",
        )
    )
    output_dir: Path = Path("outputs")

    @classmethod
    def load(cls, path: str | Path = DEFAULT_APP_CONFIG_PATH) -> "AppConfig":
        config_path = Path(path)
        with config_path.open("r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        if not isinstance(loaded, dict):
            raise ValueError(f"App config must be a mapping: {config_path}")

        strategy_data = loaded.get("strategy", {})
        execution_cost_data = loaded.get("execution_costs", {})
        if "unshortable_tickers" in execution_cost_data and isinstance(execution_cost_data["unshortable_tickers"], list):
            execution_cost_data["unshortable_tickers"] = tuple(execution_cost_data["unshortable_tickers"])
        tax_data = loaded.get("tax", {})
        paper_like_data = loaded.get("paper_like", {})
        daily_data = loaded.get("daily", {})

        return cls(
            strategy=StrategyConfig(**strategy_data),
            execution_costs=ExecutionCostConfig(**execution_cost_data),
            tax=TaxConfig(**tax_data),
            paper_like=ModeConfig(**paper_like_data),
            daily=ModeConfig(**daily_data),
            output_dir=Path(loaded.get("output_dir", "outputs")),
        )


def ensure_output_dir(path: str | Path) -> Path:
    out = Path(path)
    out.mkdir(parents=True, exist_ok=True)
    return out
