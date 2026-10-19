from pathlib import Path
from types import SimpleNamespace
from typing import cast
import json
import socket

import numpy as np
import pandas as pd
import pytest

from juslag import factor_analysis as factor
from juslag.services.data_status import build_data_status
from juslag.config import AppConfig, JP_TICKERS, US_TICKERS
from juslag.cache import PriceCache


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def files(tmp_path: Path, header: str, rows: str = "2026-10-16,0.01,0.02,0.03,0.0001,0.04\n", *, carhart=True):
    folder = tmp_path / "factors/normalized"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "ff3_metadata.json").write_text('{"source":"fixture","unit":"decimal"}')
    name = "carhart4_japan_daily.csv" if carhart else "ff3_japan_daily.csv"
    path = folder / name
    path.write_text(header + "\n" + rows)
    return path


def test_downloaded_names_preserve_values_and_expose_expected_factors(tmp_path):
    path = files(tmp_path, "date,mkt_rf,smb,hml,rf,wml")
    before = path.read_bytes()
    frame, metadata = factor.load_factor_frame(tmp_path)
    assert frame.columns.tolist() == ["MKT_RF", "SMB", "HML", "RF", "MOM"]
    assert frame.iloc[0].tolist() == [0.01, 0.02, 0.03, 0.0001, 0.04]
    assert frame.index[0] == pd.Timestamp("2026-10-16")
    assert metadata["available"] and path.read_bytes() == before


def test_case_hyphen_and_canonical_input_are_equivalent(tmp_path):
    lower = tmp_path / "lower"
    canonical = tmp_path / "canonical"
    files(lower, "date,Mkt-RF,smb,HML,rf,WML")
    files(canonical, "date,MKT_RF,SMB,HML,RF,MOM")
    first, _ = factor.load_factor_frame(lower)
    second, _ = factor.load_factor_frame(canonical)
    pd.testing.assert_frame_equal(first, second)


@pytest.mark.parametrize("header", [
    "date,MKT_RF,mkt_rf,SMB,HML", "date,mkt_rf,mkt_rf,smb,hml",
    "date,MKT_RF,SMB,HML,MOM,WML", "date,Date,MKT_RF,SMB,HML",
])
def test_ambiguous_alias_or_exact_duplicate_is_rejected_before_csv_data_read(tmp_path, monkeypatch, header):
    files(tmp_path, header, "")
    def forbidden(*args, **kwargs):
        raise AssertionError("ambiguous header reached pandas data reader")
    monkeypatch.setattr(factor.pd, "read_csv", forbidden)
    with pytest.raises(ValueError, match="Ambiguous duplicate"):
        factor.load_factor_frame(tmp_path)


def test_ff3_without_momentum_stays_ff3(tmp_path):
    files(tmp_path, "date,mkt_rf,smb,hml,rf", "2026-10-16,0.01,0.02,0.03,0.0001\n", carhart=False)
    frame, _ = factor.load_factor_frame(tmp_path)
    assert frame.columns.tolist() == ["MKT_RF", "SMB", "HML", "RF"]
    result = factor.evaluate_factor_regression_readiness(frame, pd.Series(dtype=float))
    assert not result["ready"] and result["reason"] == "returns_unavailable"


def test_metadata_or_csv_absence_stays_unavailable(tmp_path):
    frame, metadata = factor.load_factor_frame(tmp_path)
    assert frame.empty and metadata["available"] is False
    folder = tmp_path / "factors/normalized"
    folder.mkdir(parents=True)
    (folder / "ff3_metadata.json").write_text('{"source":"fixture"}')
    frame, metadata = factor.load_factor_frame(tmp_path)
    assert frame.empty and metadata["available"] is False


@pytest.mark.parametrize("n,ready", [(59, False), (60, True)])
def test_observation_threshold_is_unchanged(n, ready):
    dates = pd.date_range("2026-01-01", periods=n)
    frame = pd.DataFrame({"MKT_RF": 0.01, "SMB": 0.02, "HML": 0.03}, index=dates)
    returns = pd.Series(0.001, index=dates)
    result = factor.evaluate_factor_regression_readiness(frame, returns)
    assert result["ready"] is ready and result["n_obs"] == n


def test_regression_uses_identical_values_after_label_normalization(tmp_path):
    dates = pd.date_range("2026-01-01", periods=120)
    rng = np.random.default_rng(12)
    values = rng.normal(0, 0.01, (120, 5))
    lower = tmp_path / "lower"
    canonical = tmp_path / "canonical"
    for base, names in [(lower, ["mkt_rf", "smb", "hml", "rf", "wml"]),
                        (canonical, ["MKT_RF", "SMB", "HML", "RF", "MOM"])]:
        path = files(base, "date," + ",".join(names), "")
        pd.DataFrame(values, index=dates, columns=names).rename_axis("date").to_csv(path)
    first, _ = factor.load_factor_frame(lower)
    second, _ = factor.load_factor_frame(canonical)
    returns = pd.Series(rng.normal(0, 0.01, 120), index=dates)
    left = factor.compute_factor_regression(returns, first)
    right = factor.compute_factor_regression(returns, second)
    assert left == right
    assert left["n_obs"] == 120
    assert "ff3_regression_summary" in left and "carhart4_regression_summary" in left


def test_carhart_label_does_not_make_other_requirements_ready(tmp_path):
    files(tmp_path, "date,mkt_rf,smb,hml,rf,wml")
    actions = tmp_path / "actions/normalized"
    actions.mkdir(parents=True)
    (actions / "actions_metadata.json").write_text(json.dumps({
        "tickers_covered": list(US_TICKERS) + list(JP_TICKERS),
        "total_actions": 100, "dividends": 100, "splits": 0,
    }))
    class Cache:
        def summary(self, *args, **kwargs):
            return {"daily_signal_ready": True, "required_latest_date": "2026-10-16"}
    config = SimpleNamespace(paper_like=SimpleNamespace(sample_start="2026-01-01", sample_end=None))
    result = build_data_status(cast(PriceCache, Cache()), cast(AppConfig, config),
        external_dir=tmp_path, report_path=tmp_path / "absent.json")
    assert result["factor_data"]["model"] == "Carhart4"
    assert result["factor_regression_reason"] == "returns_unavailable"
    assert result["adjusted_series_verification_reason_code"] == "missing_date_range"
    assert not result["paper_reproduction_ready"]


def test_bom_and_leading_blank_lines_keep_existing_csv_support(tmp_path):
    path = files(tmp_path, "date,mkt_rf,smb,hml,rf,wml")
    path.write_text("\ufeff\n   \n" + path.read_text(), encoding="utf-8")
    frame, _ = factor.load_factor_frame(tmp_path)
    assert frame.columns.tolist() == ["MKT_RF", "SMB", "HML", "RF", "MOM"]
    assert frame.iloc[0].tolist() == [0.01, 0.02, 0.03, 0.0001, 0.04]
