import pandas as pd

from juslag.portfolio import _next_jp_session_values, build_portfolio


def test_next_jp_session_skips_jp_holiday_and_us_holiday() -> None:
    jp_dates = pd.to_datetime(["2025-01-10", "2025-01-14", "2025-01-15"])
    signal_dates = pd.to_datetime(["2025-01-10", "2025-01-13", "2025-01-14", "2025-01-15"])
    frame = pd.DataFrame({"A": [0.01, 0.02, 0.03]}, index=jp_dates)

    aligned = _next_jp_session_values(frame, signal_dates)

    assert aligned["A"].iloc[:3].tolist() == [0.02, 0.02, 0.03]
    assert pd.isna(aligned["A"].iloc[3])


def test_build_portfolio_returns_series_non_empty() -> None:
    idx = pd.date_range("2024-01-01", periods=5, freq="B")
    sig = pd.DataFrame(
        {
            "A": [0.9, 0.2, -0.1, 0.7, 0.1],
            "B": [-0.2, 0.8, 0.4, -0.4, 0.3],
            "C": [0.1, -0.6, 0.9, 0.2, -0.7],
            "D": [-0.7, 0.3, -0.2, 0.1, 0.8],
        },
        index=idx,
    )
    jp_oc = pd.DataFrame(
        {
            "A": [0.01, 0.02, -0.01, 0.01, 0.00],
            "B": [-0.01, 0.01, 0.01, -0.02, 0.01],
            "C": [0.00, -0.01, 0.03, 0.02, -0.01],
            "D": [0.02, -0.01, 0.00, 0.01, 0.03],
        },
        index=idx,
    )
    out = build_portfolio(sig, jp_oc, q=0.25)
    assert isinstance(out, pd.Series)
    assert len(out) > 0


def test_build_portfolio_safe_empty_when_insufficient() -> None:
    idx = pd.date_range("2024-01-01", periods=2, freq="B")
    sig = pd.DataFrame({"A": [0.1, 0.2], "B": [0.2, 0.1]}, index=idx)
    jp_oc = pd.DataFrame({"A": [0.01, 0.02], "B": [0.02, 0.01]}, index=idx)
    out = build_portfolio(sig, jp_oc, q=0.3)
    assert isinstance(out, pd.Series)
    assert out.empty
