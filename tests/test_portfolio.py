import pandas as pd

from juslag.portfolio import build_portfolio


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
