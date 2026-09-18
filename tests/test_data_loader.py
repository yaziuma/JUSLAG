from __future__ import annotations

import pandas as pd
import pytest

from juslag.data_loader import _fetch_group_with_cache, build_joint_cc, compute_returns, repair_known_bad_prices


def test_repair_bad_1629_prices_without_double_adjustment() -> None:
    dates = pd.to_datetime(["2026-03-27", "2026-03-30", "2026-03-31", "2026-04-01", "2026-04-02"])
    jp_open = pd.DataFrame({"1629.T": [284.5, 0.566, 0.5738, 287, 290]}, index=dates)
    jp_close = pd.DataFrame({"1629.T": [288.6, 0.5676, 0.5498, 288.7, 284]}, index=dates)
    clean_open, clean_close = repair_known_bad_prices(jp_open, jp_close)
    again_open, again_close = repair_known_bad_prices(clean_open, clean_close)
    _, jp_oc, jp_cc = compute_returns(pd.DataFrame(index=dates), clean_close, clean_open)

    assert jp_close.loc[dates[1], "1629.T"] == 0.5676
    assert clean_close.loc[dates[1:3], "1629.T"].tolist() == [283.8, 274.9]
    assert clean_open.loc[dates[1:3], "1629.T"].tolist() == [283.0, 286.9]
    pd.testing.assert_frame_equal(clean_open, again_open)
    pd.testing.assert_frame_equal(clean_close, again_close)
    assert jp_cc.loc[dates[1:3], "1629.T"].abs().max() < 0.05
    assert pd.notna(jp_cc.loc[dates[3], "1629.T"])
    assert pd.notna(jp_cc.loc[dates[4], "1629.T"])
    assert jp_oc.loc[dates[1:3], "1629.T"].abs().max() < 0.05


def test_unrecognized_known_bad_price_is_quarantined() -> None:
    dates = pd.to_datetime(["2026-03-30"])
    jp_open = pd.DataFrame({"1629.T": [1.0]}, index=dates)
    jp_close = pd.DataFrame({"1629.T": [1.1]}, index=dates)

    clean_open, clean_close = repair_known_bad_prices(jp_open, jp_close)

    assert pd.isna(clean_open.at[dates[0], "1629.T"])
    assert pd.isna(clean_close.at[dates[0], "1629.T"])


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


@pytest.mark.parametrize(
    ("start", "expected_download_start"),
    [
        ("2010-01-01", "2026-09-10"),
        ("2009-12-20", "2009-12-20"),
    ],
)
def test_fetch_group_treats_first_trading_day_as_covered(
    monkeypatch, start: str, expected_download_start: str,
) -> None:
    class StubCache:
        def date_range(self, ticker: str, price_mode: str):
            return "2010-01-04", "2026-09-17"

        def load(self, tickers, start, end, price_mode: str):
            return {}

    downloaded: list[tuple[str, str]] = []

    def fake_download(*args, **kwargs):
        downloaded.append((kwargs["start"], kwargs["end"]))
        return pd.DataFrame()

    monkeypatch.setattr("juslag.data_loader.yf.download", fake_download)
    _fetch_group_with_cache(["SPY"], start, "2026-09-19", StubCache())

    expected = [(expected_download_start, "2026-09-19")]
    if start == "2010-01-01":
        expected.insert(0, ("2010-01-01", "2010-01-04"))
    assert downloaded == expected


def test_fetch_group_recovers_missing_head_trading_day(monkeypatch) -> None:
    saved: list[str] = []

    class StubCache:
        def date_range(self, ticker: str, price_mode: str):
            return "2010-01-04", "2026-09-17"

        def upsert(self, ticker, open_s, close_s, price_mode: str):
            saved.extend(str(date.date()) for date in open_s.index)
            return len(open_s)

        def load(self, tickers, start, end, price_mode: str):
            return {}

    def fake_download(*args, **kwargs):
        if kwargs["end"] != "2010-01-04":
            return pd.DataFrame()
        columns = pd.MultiIndex.from_product([["Close", "Open"], ["SPY"]])
        return pd.DataFrame([[101.0, 100.0]], index=pd.to_datetime(["2010-01-02"]), columns=columns)

    monkeypatch.setattr("juslag.data_loader.yf.download", fake_download)
    _fetch_group_with_cache(["SPY"], "2010-01-01", "2026-09-19", StubCache())

    assert saved == ["2010-01-02"]
