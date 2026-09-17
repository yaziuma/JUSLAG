from __future__ import annotations

import pandas as pd

from juslag.regime import build_regime_frame


def test_regime_labels_do_not_change_when_future_data_is_appended() -> None:
    dates = pd.bdate_range("2024-01-02", periods=80)
    jp_cc = pd.DataFrame({"A": [0.001 * (i % 9 - 4) for i in range(80)]}, index=dates)
    signals = pd.DataFrame({"A": [float(i % 11) for i in range(80)], "B": [0.0] * 80}, index=dates)

    full = build_regime_frame(jp_cc, signals)
    prefix = build_regime_frame(jp_cc.iloc[:50], signals.iloc[:50])

    pd.testing.assert_frame_equal(full.iloc[:50], prefix)
