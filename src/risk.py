"""Phase 5: EWMA covariance of the 49 industry returns (CLAUDE.md 7.1).

Timing: the covariance dated month-end t uses industry returns of months up
to and including t (all observable at the end of t) and is used to size
holdings formed at t, which earn the return of t+1.

Returns are Ken French value-weighted industry returns. The plan specifies
excess returns; subtracting RF is unnecessary here because RF is common to
all industries: for dollar-neutral holdings (1'h = 0) the RF terms drop out of
h' Sigma h exactly, and residual-to-average volatility is unaffected.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src.utils import to_month_end  # noqa: E402


def returns_from_signal_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Rebuild the wide industry-return panel from a signal panel.

    `next_return` on signal month s is the industry return of month s+1, so the
    return of month m is `next_return` at signal month m-1. Output: index =
    return month (month-end), columns = industry IDs, values in decimals.
    """
    frame = panel[["month", "industry", "next_return"]].copy()
    frame["month"] = to_month_end(to_month_end(frame["month"]) + pd.offsets.MonthEnd(1))
    wide = frame.pivot(index="month", columns="industry", values="next_return")
    return wide.dropna(how="all").sort_index()


def ewma_decay(halflife: float) -> float:
    """Per-month decay factor d with d ** halflife == 0.5."""
    return 0.5 ** (1.0 / halflife)


def ewma_covariances(returns: pd.DataFrame,
                     halflife: float = config.COV_HALFLIFE_MONTHS,
                     min_months: int = config.COV_MIN_MONTHS
                     ) -> dict[pd.Timestamp, np.ndarray]:
    """Exponentially weighted covariance at each month-end, monthly units.

    Input: wide return panel (month x industry). Estimation starts at the
    first month where every industry has a return; a month with any missing
    return ends the run (it never occurs after 1969 in Ken French data).
    The month-t estimate weights the return of month t-k by d**k (d from the
    half-life), normalizes weights to sum to one, and centers on the
    EWMA mean. Months with fewer than `min_months` returns get no estimate.

    Output: {month-end t: covariance array (industries ordered as columns)}.
    """
    complete = returns.notna().all(axis=1)
    if not complete.any():
        return {}
    data = returns.loc[complete.idxmax():]
    d = ewma_decay(halflife)
    n = data.shape[1]
    weight_sum, first_moment, second_moment = 0.0, np.zeros(n), np.zeros((n, n))
    out = {}
    for count, (month, row) in enumerate(data.iterrows(), start=1):
        x = row.to_numpy(dtype=float)
        if not np.isfinite(x).all():
            break
        weight_sum = d * weight_sum + 1.0
        first_moment = d * first_moment + x
        second_moment = d * second_moment + np.outer(x, x)
        if count >= min_months:
            mean = first_moment / weight_sum
            out[month] = second_moment / weight_sum - np.outer(mean, mean)
    return out


def shrink_covariance(cov: np.ndarray,
                      intensity: float = config.COV_SHRINKAGE) -> np.ndarray:
    """Shrink a covariance toward its diagonal: (1-k) Sigma + k diag(Sigma).

    Variances are unchanged; every covariance is scaled by (1 - k). This damps
    the low-variance directions a 49x49 estimate understates, which a
    mean-variance optimizer would otherwise lever (CLAUDE.md 7.1 team decision).
    """
    if not 0 <= intensity <= 1:
        raise ValueError("shrinkage intensity must be in [0, 1]")
    return (1 - intensity) * cov + intensity * np.diag(np.diag(cov))


def market_betas(cov: np.ndarray) -> np.ndarray:
    """Beta of each industry to the equal-weighted industry average.

    beta_n = cov(r_n, r_m) / var(r_m) with r_m = mean_n r_n, from the given
    covariance. The equal-weighted average is the market proxy because the
    signal panel carries no industry market caps (CLAUDE.md 7.3 robustness).
    """
    n = cov.shape[0]
    w = np.full(n, 1.0 / n)
    return cov @ w / (w @ cov @ w)


def residual_volatility(cov: np.ndarray, annualize: bool = True) -> np.ndarray:
    """Volatility of each industry's return minus the equal-weighted average.

    omega_n = sqrt(diag(A Sigma A')) with A = I - 11'/N (CLAUDE.md 7.2).
    Annualized by sqrt(12) when `annualize`.
    """
    n = cov.shape[0]
    demean = np.eye(n) - np.full((n, n), 1.0 / n)
    variance = np.diag(demean @ cov @ demean.T).clip(min=0)
    scale = config.ANNUALIZE if annualize else 1
    return np.sqrt(variance * scale)
