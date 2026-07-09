from pathlib import Path

from juslag.config import AppConfig, ExecutionCostConfig, StrategyConfig, TaxConfig


def test_strategy_config_defaults() -> None:
    cfg = StrategyConfig()
    assert cfg.window_l == 60
    assert cfg.k_factors == 3
    assert cfg.lambda_reg == 0.9
    assert cfg.operation_mode == "production"


def test_app_config_output_dir() -> None:
    cfg = AppConfig()
    assert str(cfg.output_dir)


def test_app_config_loads_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "app.yaml"
    config_path.write_text(
        "\n".join(
            [
                "strategy:",
                "  window_l: 90",
                "  k_factors: 4",
                "  lambda_reg: 1.2",
                "  quantile_q: 0.25",
                "  operation_mode: development",
                "paper_like:",
                "  name: paper_like",
                "  sample_start: '2019-01-01'",
                "  sample_end: '2025-12-31'",
                "  pretrain_end: '2021-12-31'",
                "daily:",
                "  name: daily",
                "  sample_start: '2019-01-01'",
                "  sample_end:",
                "  pretrain_end: '2021-12-31'",
                "output_dir: run-outputs",
            ]
        ),
        encoding="utf-8",
    )

    cfg = AppConfig.load(config_path)

    assert cfg.strategy == StrategyConfig(window_l=90, k_factors=4, lambda_reg=1.2, quantile_q=0.25, operation_mode="development")
    assert str(cfg.output_dir) == "run-outputs"


def test_new_configs_default_values() -> None:
    exec_cfg = ExecutionCostConfig()
    tax_cfg = TaxConfig()

    assert exec_cfg.commission_bps_per_side == 5.0
    assert exec_cfg.slippage_bps_per_side == 5.0
    assert exec_cfg.allow_short is True
    assert tax_cfg.tax_rate == 0.20315
    assert tax_cfg.tax_model == "annual_net"
