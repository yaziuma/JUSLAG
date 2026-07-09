from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class RegressionSummary:
    alpha: float
    betas: dict[str, float]
    t_stats: dict[str, float]
    r_squared: float
    n_obs: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "alpha": self.alpha,
            "betas": self.betas,
            "t_stats": self.t_stats,
            "r_squared": self.r_squared,
            "n_obs": self.n_obs,
        }


def _ols(y: pd.Series, x: pd.DataFrame) -> RegressionSummary:
    X = np.column_stack([np.ones(len(x)), x.values])
    Y = y.values.reshape(-1, 1)
    beta = np.linalg.lstsq(X, Y, rcond=None)[0].flatten()
    resid = Y.flatten() - X @ beta
    n = len(Y)
    k = X.shape[1]
    sigma2 = float((resid @ resid) / max(1, (n - k)))
    cov = sigma2 * np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(cov))
    tvals = beta / np.where(se == 0, np.nan, se)
    y_hat = X @ beta
    sst = float(np.sum((Y.flatten() - float(np.mean(Y))) ** 2))
    sse = float(np.sum((Y.flatten() - y_hat) ** 2))
    r2 = 1.0 - (sse / sst) if sst > 0 else 0.0
    betas = {col: float(beta[i + 1]) for i, col in enumerate(x.columns)}
    t_stats = {"alpha": float(tvals[0])}
    t_stats.update({col: float(tvals[i + 1]) for i, col in enumerate(x.columns)})
    return RegressionSummary(alpha=float(beta[0]), betas=betas, t_stats=t_stats, r_squared=r2, n_obs=n)


def load_factor_frame(base: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    meta_path = base / "factors" / "normalized" / "ff3_metadata.json"
    if not meta_path.exists():
        return pd.DataFrame(), {"available": False}
    meta = pd.read_json(meta_path, typ="series").to_dict()
    carhart_path = base / "factors" / "normalized" / "carhart4_japan_daily.csv"
    ff3_path = base / "factors" / "normalized" / "ff3_japan_daily.csv"
    path = carhart_path if carhart_path.exists() else ff3_path
    if not path.exists():
        return pd.DataFrame(), {"available": False}
    f = pd.read_csv(path)
    date_col = "date" if "date" in f.columns else f.columns[0]
    f[date_col] = pd.to_datetime(f[date_col])
    f = f.rename(columns={date_col: "date"}).set_index("date").sort_index()
    return f, {"available": True, "path": str(path), "metadata": meta}


def compute_factor_regression(signal_returns: pd.Series, factor_df: pd.DataFrame) -> dict[str, Any]:
    if signal_returns.empty or factor_df.empty:
        return {}
    if not isinstance(signal_returns.index, pd.DatetimeIndex):
        signal_returns.index = pd.to_datetime(signal_returns.index)
    merged = pd.DataFrame({"strategy": signal_returns}).join(factor_df, how="inner").dropna()
    if merged.empty:
        return {}
    out: dict[str, Any] = {"date_range": {"start": str(merged.index.min().date()), "end": str(merged.index.max().date())}, "n_obs": int(len(merged))}
    ff3_cols = [c for c in ["MKT_RF", "SMB", "HML"] if c in merged.columns]
    if len(ff3_cols) == 3:
        out["ff3_regression_summary"] = _ols(merged["strategy"], merged[ff3_cols]).to_dict()
    carhart_cols = [c for c in ["MKT_RF", "SMB", "HML", "MOM"] if c in merged.columns]
    if len(carhart_cols) == 4:
        out["carhart4_regression_summary"] = _ols(merged["strategy"], merged[carhart_cols]).to_dict()
    return out


def evaluate_factor_regression_readiness(factor_df: pd.DataFrame, returns: pd.Series, min_obs: int = 60) -> dict[str, Any]:
    if factor_df.empty:
        return {"ready": False, "reason": "factor_data_unavailable", "n_obs": 0}
    required_cols = {"MKT_RF", "SMB", "HML"}
    missing = sorted(required_cols - set(factor_df.columns))
    if missing:
        return {"ready": False, "reason": f"missing_columns:{','.join(missing)}", "n_obs": 0}
    if returns.empty:
        return {"ready": False, "reason": "returns_unavailable", "n_obs": 0}
    merged = pd.DataFrame({"strategy": returns}).join(factor_df, how="inner").dropna()
    n_obs = int(len(merged))
    if n_obs < min_obs:
        return {"ready": False, "reason": f"insufficient_observations:{n_obs}", "n_obs": n_obs}
    return {"ready": True, "reason": "ok", "n_obs": n_obs, "start": str(merged.index.min().date()), "end": str(merged.index.max().date())}
