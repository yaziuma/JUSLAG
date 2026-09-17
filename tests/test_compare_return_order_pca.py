import runpy
from pathlib import Path

import numpy as np
import pandas as pd

from juslag.config import JP_TICKERS, US_TICKERS

paired_pca_returns = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/reports/compare_return_order_pca.py")
)["paired_pca_returns"]


def test_identical_calendars_produce_identical_pca_pnl() -> None:
    us, jp = list(US_TICKERS), list(JP_TICKERS)
    dates = pd.bdate_range("2025-01-01", periods=85)
    rng = np.random.default_rng(42)
    steps = rng.normal(0, 0.01, size=(len(dates), len(us) + len(jp)))
    close = pd.DataFrame(100 * np.exp(steps.cumsum(axis=0)), index=dates, columns=us + jp)
    open_ = close * (1 + rng.normal(0, 0.003, size=close.shape))

    paired = paired_pca_returns(close, open_, us, jp, str(dates[65].date()), str(dates[70].date()))

    assert not paired.empty
    pd.testing.assert_series_equal(paired["common_first"], paired["market_first"], check_names=False)
