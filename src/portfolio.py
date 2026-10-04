"""Phase 5: alphas -> holdings and lambda calibration (CLAUDE.md 7.2-7.4).

Timing: holdings dated month-end t use only the z-scores formed at t, the EWMA
covariance from returns through t, and ICs of signal months before t (whose
t+1 outcomes are known by t). They earn the industry return of month t+1.

Units: covariance, volatilities, alphas, and the risk target are annualized.
Holdings are active weights (fractions of capital) in a dollar-neutral book.

Choices not fixed by the plan (recorded in README):
- Industries whose signal is missing at t are excluded from that month's
  portfolio (weight 0), not given a neutral alpha.
- The IC in alpha = IC * omega * z is the strategy's own expanding mean
  Spearman IC over signal months before t, requiring ALPHA_IC_MIN_MONTHS.
  Because lambda is recalibrated to the risk target every month, only its
  sign affects the holdings; a negative IC means the signal is traded short.
- Risk model: EWMA covariance shrunk toward its diagonal (config.COV_SHRINKAGE,
  team decision) for optimization and risk; omega uses the raw EWMA.
- The cap |h_n| <= 10% of gross exposure is scale-free but not convex, so it
  is solved as a fixed point: solve with an absolute cap c, set
  c = cap * gross, repeat until consistent.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src import risk  # noqa: E402
from src.ic import monthly_information_coefficients  # noqa: E402
from src.utils import to_month_end  # noqa: E402


# --------------------------------------------------------------------------
# Building blocks
# --------------------------------------------------------------------------
def expanding_mean_ic(monthly_ic: pd.DataFrame, signal: str,
                      months: pd.Index,
                      min_months: int = config.ALPHA_IC_MIN_MONTHS) -> pd.Series:
    """Mean Spearman IC of `signal` over signal months strictly before each t.

    Output: Series indexed by `months`; NaN until `min_months` ICs exist.
    """
    series = (monthly_ic.loc[monthly_ic["signal"].eq(signal)]
              .set_index("month")["spearman_ic"].dropna().sort_index())
    out = {}
    for month in months:
        past = series.loc[series.index < month]
        out[month] = past.mean() if len(past) >= min_months else np.nan
    return pd.Series(out, dtype=float)


def grinold_kahn_alpha(z: np.ndarray, ic: float, omega: np.ndarray) -> np.ndarray:
    """alpha_n = IC * omega_n * z_n, demeaned so alphas sum to zero (7.2)."""
    alpha = ic * omega * z
    return alpha - alpha.mean()


def _constraint_matrix(n: int, extra: np.ndarray | None) -> np.ndarray:
    """Rows of the equality constraints A h = 0: dollar neutrality, plus any
    extra exposures (e.g. market betas) to neutralize."""
    rows = [np.ones(n)]
    if extra is not None:
        rows += list(np.atleast_2d(extra))
    return np.vstack(rows)


def _unconstrained_dollar_neutral(alpha: np.ndarray, cov: np.ndarray,
                                  extra: np.ndarray | None = None) -> np.ndarray:
    """argmax alpha'h - h' cov h  s.t. A h = 0  (lambda = 1).

    A always includes 1' (dollar neutral); `extra` adds rows such as betas.
    Closed form: h = 1/2 Sigma^-1 (alpha - A' mu), A Sigma^-1 A' mu = A Sigma^-1 alpha.
    """
    a = _constraint_matrix(len(alpha), extra)
    inv_alpha = np.linalg.solve(cov, alpha)
    inv_at = np.linalg.solve(cov, a.T)
    mu = np.linalg.lstsq(a @ inv_at, a @ inv_alpha, rcond=None)[0]
    return 0.5 * (inv_alpha - inv_at @ mu)


def _box_dollar_neutral(alpha: np.ndarray, cov: np.ndarray, cap: float,
                        start: np.ndarray, extra: np.ndarray | None = None) -> np.ndarray:
    """argmax alpha'h - h' cov h  s.t. A h = 0, |h_n| <= cap  (lambda = 1)."""
    n = len(alpha)
    a = _constraint_matrix(n, extra)
    x0 = np.clip(start, -cap, cap)
    x0 = x0 - x0.mean()
    x0 = np.clip(x0, -cap, cap)
    result = minimize(
        lambda h: h @ cov @ h - alpha @ h, x0,
        jac=lambda h: 2 * cov @ h - alpha,
        method="SLSQP", bounds=[(-cap, cap)] * n,
        constraints=[{"type": "eq", "fun": lambda h: a @ h, "jac": lambda h: a}],
        options={"ftol": 1e-14, "maxiter": 500},
    )
    return result.x


def capped_mean_variance(alpha: np.ndarray, cov: np.ndarray,
                         cap_frac: float = config.POSITION_CAP_FRAC_GROSS,
                         max_iter: int = 200,
                         extra: np.ndarray | None = None) -> tuple[np.ndarray, bool]:
    """Mean-variance holdings at lambda = 1 with 1'h = 0 and |h_n| <= cap * gross.

    `extra` adds equality constraints extra @ h = 0 (e.g. zero market beta).
    Returns (holdings, converged). Scaling the result by 1/lambda gives the
    solution for any lambda, since all constraints are scale-free.
    """
    h = _unconstrained_dollar_neutral(alpha, cov, extra)
    gross = np.abs(h).sum()
    if gross == 0 or np.abs(h).max() <= cap_frac * gross * (1 + config.CAP_TOL):
        return h, True
    cap = cap_frac * gross
    for _ in range(max_iter):
        h = _box_dollar_neutral(alpha, cov, cap, h, extra)
        new_cap = cap_frac * np.abs(h).sum()
        if abs(new_cap - cap) <= 1e-10 * max(cap, 1e-12):
            break
        cap = new_cap
    gross = np.abs(h).sum()
    converged = np.abs(h).max() <= cap_frac * gross * (1 + 1e-4)
    return h, bool(converged)


def diagonal_holdings(alpha: np.ndarray, omega: np.ndarray) -> np.ndarray:
    """HW02 comparison: h_n = alpha_n / (2 omega_n^2) at lambda = 1, demeaned
    so the book is dollar neutral. No position cap."""
    h = alpha / (2 * omega ** 2)
    return h - h.mean()


def calibrate_to_target(h_unit: np.ndarray, cov: np.ndarray,
                        target: float = config.TARGET_ACTIVE_RISK
                        ) -> tuple[np.ndarray, float, float]:
    """Scale lambda = 1 holdings so ex-ante risk sqrt(h' cov h) equals target.

    Returns (holdings, lambda, ex-ante risk). h(lambda) = h_unit / lambda, so
    lambda = sqrt(h_unit' cov h_unit) / target.
    """
    unit_risk = float(np.sqrt(h_unit @ cov @ h_unit))
    if not np.isfinite(unit_risk) or unit_risk <= 0:
        return np.full_like(h_unit, np.nan), np.nan, np.nan
    lam = unit_risk / target
    h = h_unit / lam
    return h, lam, float(np.sqrt(h @ cov @ h))


# --------------------------------------------------------------------------
# Monthly loop
# --------------------------------------------------------------------------
def build_holdings(panel: pd.DataFrame,
                   strategies: dict[str, str] = config.STRATEGY_SIGNALS,
                   halflife: float = config.COV_HALFLIFE_MONTHS,
                   target: float = config.TARGET_ACTIVE_RISK,
                   ic_min_months: int = config.ALPHA_IC_MIN_MONTHS,
                   shrinkage: float = config.COV_SHRINKAGE,
                   beta_neutral: bool = False,
                   methods: tuple[str, ...] = ("mv", "diag"),
                   ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Form monthly holdings for each strategy, mean-variance and diagonal.

    Input: Phase 4 signal panel (month, industry, z-score columns,
    next_return). Output: (holdings long table, per-month diagnostics).
    Holdings rows: month, strategy, method, industry, alpha, weight.
    Diagnostics include lambda, ex-ante risk, gross, cap check, and the
    realized active return of month t+1 (NaN when not yet observed).
    The optimizer, risk calibration, and ex-ante risk use the EWMA covariance
    shrunk toward its diagonal by `shrinkage`; omega uses the raw EWMA.
    With `beta_neutral`, the mean-variance book also has zero beta to the
    equal-weighted industry average (risk.market_betas); `beta_exposure` in
    the diagnostics reports beta'h for every book.
    """
    panel = panel.copy()
    panel["month"] = to_month_end(panel["month"])
    returns = risk.returns_from_signal_panel(panel)
    industries = list(returns.columns)
    covs = risk.ewma_covariances(returns, halflife=halflife)
    monthly_ic = monthly_information_coefficients(panel, score_columns=strategies)
    min_assets = math.ceil(1 / config.POSITION_CAP_FRAC_GROSS)

    by_month = {m: g.set_index("industry") for m, g in panel.groupby("month")}
    holding_rows, diag_rows = [], []
    for strategy, column in strategies.items():
        months = pd.Index(sorted(m for m in by_month if m in covs))
        ic_series = expanding_mean_ic(monthly_ic, strategy, months, ic_min_months)
        for month in months:
            group = by_month[month].reindex(industries)
            z_all = group[column].to_numpy(dtype=float)
            available = np.isfinite(z_all)
            ic = ic_series.get(month, np.nan)
            if available.sum() < min_assets or not np.isfinite(ic) or ic == 0:
                continue
            cov_ann = risk.shrink_covariance(covs[month], shrinkage) * config.ANNUALIZE
            omega = risk.residual_volatility(covs[month])[available]
            sub_cov = cov_ann[np.ix_(available, available)]
            alpha = grinold_kahn_alpha(z_all[available], ic, omega)
            next_ret = group["next_return"].to_numpy(dtype=float)[available]
            ids = np.array(industries)[available]
            betas = risk.market_betas(covs[month])[available]
            for method in methods:
                if method == "mv":
                    unit, converged = capped_mean_variance(
                        alpha, sub_cov, extra=betas if beta_neutral else None)
                else:
                    unit, converged = diagonal_holdings(alpha, omega), True
                h, lam, exante = calibrate_to_target(unit, sub_cov, target)
                gross = np.abs(h).sum()
                realized = float(h @ next_ret) if np.isfinite(next_ret).all() else np.nan
                diag_rows.append({
                    "month": month, "strategy": strategy, "method": method,
                    "n_industries": int(available.sum()), "ic_used": ic,
                    "lambda": lam, "exante_active_risk_ann": exante,
                    "gross_exposure": gross, "net_exposure": h.sum(),
                    "beta_exposure": float(betas @ h),
                    "max_weight_frac_gross": np.abs(h).max() / gross,
                    "n_at_cap": int(np.sum(np.abs(h) >= config.POSITION_CAP_FRAC_GROSS
                                           * gross * (1 - 1e-6))),
                    "cap_converged": converged,
                    "realized_active_return_next": realized,
                })
                holding_rows.append(pd.DataFrame({
                    "month": month, "strategy": strategy, "method": method,
                    "industry": ids, "alpha_ann": alpha, "weight": h,
                }))
    holdings = pd.concat(holding_rows, ignore_index=True) if holding_rows else pd.DataFrame()
    return holdings, pd.DataFrame(diag_rows)


def risk_summary(diagnostics: pd.DataFrame,
                 target: float = config.TARGET_ACTIVE_RISK) -> pd.DataFrame:
    """Ex-ante vs. realized annualized active risk per strategy and method.

    Realized active volatility = std of monthly h(t)'r(t+1) * sqrt(12).
    """
    rows = []
    for (strategy, method), g in diagnostics.groupby(["strategy", "method"], sort=False):
        realized = g["realized_active_return_next"].dropna()
        rows.append({
            "strategy": strategy, "method": method,
            "first_month": g["month"].min(), "last_month": g["month"].max(),
            "months": len(g), "months_with_realized": len(realized),
            "target_active_risk_ann": target,
            "exante_active_risk_ann_mean": g["exante_active_risk_ann"].mean(),
            "exante_max_abs_error": (g["exante_active_risk_ann"] - target).abs().max(),
            "realized_active_vol_ann": realized.std(ddof=1) * np.sqrt(config.ANNUALIZE),
            "realized_to_target_ratio":
                realized.std(ddof=1) * np.sqrt(config.ANNUALIZE) / target,
            "lambda_median": g["lambda"].median(),
            "lambda_p10": g["lambda"].quantile(0.10),
            "lambda_p90": g["lambda"].quantile(0.90),
            "gross_exposure_mean": g["gross_exposure"].mean(),
            "max_weight_frac_gross_max": g["max_weight_frac_gross"].max(),
            "cap_not_converged_months": int((~g["cap_converged"]).sum()),
        })
    return pd.DataFrame(rows)


def plot_lambda(diagnostics: pd.DataFrame, path: Path) -> Path:
    """Implied lambda over time for each strategy (mean-variance method)."""
    from src import plots

    mv = diagnostics.loc[diagnostics["method"].eq("mv")]
    fig, ax = plots.new_figure()
    labels = {"mom": "MOM", "rev": "REV", "rev_orth": "REV orthogonal", "blend": "Blend"}
    for i, (strategy, g) in enumerate(mv.groupby("strategy", sort=False)):
        ax.plot(g["month"], g["lambda"], color=plots.SERIES[i], linewidth=1.4,
                label=labels.get(strategy, strategy))
    ax.set_yscale("log")
    return plots.finish(
        fig, ax,
        title=f"Implied risk aversion λ at {config.TARGET_ACTIVE_RISK:.0%} ex-ante active "
              f"risk, {mv['month'].min():%b %Y}–{mv['month'].max():%b %Y}",
        xlabel="Portfolio formation month (month-end)",
        ylabel="λ (annualized units, log scale)",
        path=path)


def main() -> None:
    """Build Phase 5 holdings from the Phase 4 panel and save outputs."""
    panel = pd.read_parquet(config.DATA_PROCESSED / "signals_phase4.parquet")
    holdings, diagnostics = build_holdings(panel)
    config.DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    holdings.to_parquet(config.DATA_PROCESSED / "holdings.parquet",
                        compression="zstd", index=False)
    config.TABLES.mkdir(parents=True, exist_ok=True)
    diagnostics.to_csv(config.TABLES / "portfolio_by_month.csv", index=False)
    summary = risk_summary(diagnostics)
    summary.to_csv(config.TABLES / "portfolio_risk_summary.csv", index=False)
    plot_lambda(diagnostics, config.FIGURES / "lambda_over_time.png")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
