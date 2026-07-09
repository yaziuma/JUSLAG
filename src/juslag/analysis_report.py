from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from juslag.factor_analysis import compute_factor_regression, load_factor_frame, evaluate_factor_regression_readiness


def enrich_report_with_factor_analysis(report_payload: dict[str, Any], base_external: Path) -> dict[str, Any]:
    factor_df, factor_meta = load_factor_frame(base_external)
    report_payload["factor_source"] = factor_meta
    reg = {}
    regression_status = {"computed": False, "ready": False, "reason": "factor_data_unavailable", "n_obs": 0}
    if factor_meta.get("available"):
        rows = report_payload.get("rows") or []
        if rows:
            perf = pd.DataFrame(rows)
            if "date" in perf.columns and "ret_sub" in perf.columns:
                perf["date"] = pd.to_datetime(perf["date"])
                perf = perf.set_index("date").sort_index()
                readiness = evaluate_factor_regression_readiness(factor_df, perf["ret_sub"])
                regression_status = {"computed": bool(readiness.get("ready")), "ready": bool(readiness.get("ready")), "reason": readiness.get("reason"), "n_obs": readiness.get("n_obs", 0), "start": readiness.get("start"), "end": readiness.get("end")}
                if readiness.get("ready"):
                    reg = compute_factor_regression(perf["ret_sub"], factor_df)
            else:
                regression_status = {"computed": False, "ready": False, "reason": "missing_columns", "n_obs": 0}
        else:
            regression_status = {"computed": False, "ready": False, "reason": "returns_unavailable", "n_obs": 0}
    report_payload["ff3_regression_summary"] = reg.get("ff3_regression_summary", report_payload.get("ff3_regression_summary") or {})
    report_payload["carhart4_regression_summary"] = reg.get("carhart4_regression_summary", report_payload.get("carhart4_regression_summary") or {})
    report_payload["factor_regression"] = {
        "ff3": report_payload["ff3_regression_summary"] or None,
        "carhart4": report_payload["carhart4_regression_summary"] or None,
    }
    report_payload["factor_regression_status"] = regression_status
    report_payload["factor_regression_context"] = {
        "factor_file_path": factor_meta.get("path"),
        "date_range": reg.get("date_range"),
        "n_obs": reg.get("n_obs", regression_status.get("n_obs", 0)),
        "readiness_reason": regression_status.get("reason"),
    }
    return report_payload
