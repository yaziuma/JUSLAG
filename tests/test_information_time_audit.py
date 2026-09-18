from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/reports/audit_information_time.py"
SPEC = spec_from_file_location("audit_information_time", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_audit_dates_handles_us_only_day_and_jp_holiday() -> None:
    us = pd.DatetimeIndex(["2025-01-09", "2025-01-10", "2025-01-13", "2025-01-14"])
    jp = pd.DatetimeIndex(["2025-01-09", "2025-01-10", "2025-01-14", "2025-01-15"])

    rows = MODULE.audit_dates(us, jp, pretrain_end="2024-12-31", window=2, start="2025-01-01")

    assert rows[0]["signal_date"] == "2025-01-13"
    assert rows[0]["signal_path"] == "not_historical_signal"
    assert rows[0]["last_jp_input_date"] == "2025-01-10"
    assert rows[0]["execution_jp_date"] == "2025-01-14"
    assert rows[0]["date_order"] == "ok"
    assert rows[0]["decision_deadline_jst"] == "2025-01-14 08:00 JST"
    assert rows[0]["gap_observable_at"] == "2025-01-14 JP open or later"
    assert rows[0]["assumed_fill_at"] == "2025-01-14 JP open"
    assert rows[0]["audit_result"] == "not_historical_signal"
    assert rows[-1]["execution_jp_date"] == "2025-01-15"
    assert all(row["gap_after_open_fill"] == "unverified_same_open_assumption" for row in rows)


def test_audit_dates_fails_without_next_jp_session() -> None:
    us = pd.DatetimeIndex(["2025-01-09", "2025-01-10", "2025-01-13"])
    jp = pd.DatetimeIndex(["2025-01-09", "2025-01-10", "2025-01-13"])

    rows = MODULE.audit_dates(us, jp, pretrain_end="2024-12-31", window=2, start="2025-01-01")

    assert rows[0]["execution_jp_date"] == ""
    assert rows[0]["date_order"] == "fail"
    assert rows[0]["audit_result"] == "blocked_date_order"


def test_audit_uses_actual_joint_training_rows() -> None:
    us = pd.DatetimeIndex(["2025-01-09", "2025-01-10", "2025-01-13", "2025-01-14"])
    jp = us
    joint = pd.DatetimeIndex(["2025-01-09", "2025-01-13", "2025-01-14"])

    rows = MODULE.audit_dates(us, jp, pretrain_end="2024-12-31", window=1,
                              start="2025-01-10", training_dates=joint)

    assert rows[0]["signal_date"] == "2025-01-10"
    assert rows[0]["signal_path"] == "not_historical_signal"
    assert rows[1]["last_training_common_date"] == "2025-01-09"
    assert rows[0]["audit_result"] == "not_historical_signal"


def test_market_close_schedule_is_before_next_jp_deadline() -> None:
    us = pd.DatetimeIndex(["2025-01-06", "2025-01-07", "2025-01-08"])
    jp = pd.DatetimeIndex(["2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09"])
    rows = MODULE.audit_dates(
        us, jp, pretrain_end="2024-12-31", window=2, start="2025-01-08",
        us_close_times=MODULE.market_close_times("NYSE", "2025-01-06", "2025-01-09"),
        jp_close_times=MODULE.market_close_times("JPX", "2025-01-06", "2025-01-09"),
    )

    assert rows[0]["market_close_before_deadline"] == "yes"
    assert rows[0]["us_market_close_jst"].startswith("2025-01-09T06:00")


def test_latest_input_observation_must_precede_deadline() -> None:
    us = pd.DatetimeIndex(["2025-01-06", "2025-01-07", "2025-01-08"])
    jp = us.append(pd.DatetimeIndex(["2025-01-09"]))
    before = pd.Timestamp("2025-01-08T22:00:00+00:00")
    observed = {(ticker, "2025-01-08"): before for ticker in MODULE.US_TICKERS | MODULE.JP_TICKERS}
    params = dict(pretrain_end="2024-12-31", window=2, start="2025-01-08")

    rows = MODULE.audit_dates(us, jp, last_observed_at=observed, **params)
    assert rows[0]["latest_input_observation_status"] == "recorded_before_deadline"

    observed[(next(iter(MODULE.US_TICKERS)), "2025-01-08")] = pd.Timestamp("2025-01-09T00:00:00+00:00")
    rows = MODULE.audit_dates(us, jp, last_observed_at=observed, **params)
    assert rows[0]["latest_input_observation_status"] == "observed_after_deadline"
