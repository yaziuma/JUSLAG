from __future__ import annotations

import numpy as np
import pandas as pd

from juslag.metrics import compute_performance


REQUIRED_KEYS = {"Strategy", "AR(%)", "Risk(%)", "R/R", "MDD(%)", "N_days"}


def test_compute_performance_returns_required_keys_on_normal_input() -> None:
    returns = pd.Series([0.01, -0.002, 0.004, 0.003])

    perf = compute_performance(returns, label="Sample")

    assert set(perf.keys()) == REQUIRED_KEYS
    assert perf["Strategy"] == "Sample"
    assert perf["N_days"] == 4


def test_compute_performance_returns_required_keys_on_empty_input() -> None:
    returns = pd.Series([], dtype=float)

    perf = compute_performance(returns, label="Empty")

    assert set(perf.keys()) == REQUIRED_KEYS
    assert perf["Strategy"] == "Empty"
    assert perf["N_days"] == 0
    assert np.isnan(perf["AR(%)"])
    assert np.isnan(perf["Risk(%)"])
    assert np.isnan(perf["R/R"])
    assert np.isnan(perf["MDD(%)"])
