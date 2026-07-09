from __future__ import annotations

import pandas as pd

from juslag.data_loader import _fetch_group_with_cache, build_joint_cc


REQUIRED_KEYS = {
    "sample_start",
    "sample_end",
    "fill_policy",
    "price_mode",
    "filled_cells",
    "dropped_us_tickers",
    "dropped_jp_tickers",
    "effective_start",
    "effective_end",
    "joint_rows",
    "effective_window_days",
    "usable_us_tickers",
    "usable_jp_tickers",
    "cache_first_date",
    "cache_last_date",
    "cache_price_mode",
    "cache_isolated_by_price_mode",
}


def _sample_returns() -> tuple[pd.DataFrame, pd.DataFrame]:
    idx = pd.date_range("2026-01-01", periods=5, freq="D")
    us_cc = pd.DataFrame(
        {"SPY": [0.01, 0.02, None, 0.01, 0.0], "QQQ": [0.01, 0.02, 0.01, 0.0, 0.02]},
        index=idx,
    )
    jp_cc = pd.DataFrame(
        {"1306.T": [0.0, 0.01, 0.02, None, 0.01], "1321.T": [0.0, 0.01, 0.01, 0.02, 0.01]},
        index=idx,
    )
    return us_cc, jp_cc


def test_build_joint_cc_strict_does_not_fill() -> None:
    us_cc, jp_cc = _sample_returns()

    joint, quality = build_joint_cc(
        us_cc, jp_cc, fill_policy="strict", us_ratio=0.5, jp_ratio=0.5, sample_start="2026-01-01", sample_end="2026-01-31"
    )

    assert quality["fill_policy"] == "strict"
    assert quality["filled_cells"] == 0
    assert len(joint) == 3


def test_build_joint_cc_rolling_mean_reports_filled_cells() -> None:
    us_cc, jp_cc = _sample_returns()

    joint, quality = build_joint_cc(
        us_cc, jp_cc, fill_policy="rolling_mean", us_ratio=0.5, jp_ratio=0.5, sample_start="2026-01-01", sample_end="2026-01-31"
    )

    assert quality["fill_policy"] == "rolling_mean"
    assert quality["filled_cells"] > 0
    assert len(joint) >= 4


def test_build_joint_cc_quality_has_required_keys() -> None:
    us_cc, jp_cc = _sample_returns()

    _, quality = build_joint_cc(
        us_cc, jp_cc, fill_policy="strict", us_ratio=0.5, jp_ratio=0.5, sample_start="2026-01-01", sample_end="2026-01-31", price_mode="raw"
    )

    assert REQUIRED_KEYS.issubset(set(quality.keys()))
    assert quality["price_mode"] == "raw"
    assert quality["cache_price_mode"] == "raw"
    assert quality["cache_isolated_by_price_mode"] is True


def test_fetch_group_with_cache_passes_price_mode(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    class StubCache:
        def date_range(self, ticker: str, price_mode: str):
            calls.append(("date_range", price_mode))
            return None, None

        def upsert(self, ticker, open_s, close_s, price_mode: str):
            calls.append(("upsert", price_mode))
            return 1

        def load(self, tickers, start, end, price_mode: str):
            calls.append(("load", price_mode))
            idx = pd.to_datetime(["2026-01-02"])
            return {
                t: pd.DataFrame({"open": [100.0], "close": [101.0]}, index=idx)
                for t in tickers
            }

    def fake_download(*args, **kwargs):
        idx = pd.to_datetime(["2026-01-02"])
        cols = pd.MultiIndex.from_product([["Close", "Open"], ["SPY"]])
        return pd.DataFrame([[101.0, 100.0]], index=idx, columns=cols)

    monkeypatch.setattr("juslag.data_loader.yf.download", fake_download)

    _fetch_group_with_cache(["SPY"], "2026-01-01", "2026-01-10", StubCache(), price_mode="raw")

    assert ("date_range", "raw") in calls
    assert ("upsert", "raw") in calls
    assert ("load", "raw") in calls
