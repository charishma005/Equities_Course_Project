"""Phase 7: factor attribution of strategy returns (CLAUDE.md 9).

Regresses monthly net returns (base cost, config.BASE_COST_BPS) of each
strategy on Fama-French factors with Newey-West standard errors:
  ff5_umd       Mkt-RF, SMB, HML, RMW, CMA, UMD   (primary, 6 factors)
  ff5           the same without UMD             (with/without-UMD comparison)
  ff5_umd_strev 6 factors plus short-term reversal (robustness, 7 factors)

Timing: a strategy return dated return month t+1 (holdings formed at t) is
matched to factor returns of the same calendar month t+1. Every strategy
return month must exist in the factor data, or the run stops (no silent
off-by-one or dropped months). The books are dollar neutral, so their
returns are already excess returns and RF is not subtracted.

Windows follow Phase 6 (formation month): full own history, common,
post_2010, and the fixed recent 18 months (low power; reported anyway).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src.backtest import window_bounds  # noqa: E402
from src.utils import to_month_end  # noqa: E402

FF5 = ["Mkt-RF", "SMB", "HML", "RMW", "CMA"]
SPECS = {
    "ff5_umd": FF5 + ["UMD"],
    "ff5": FF5,
    "ff5_umd_strev": FF5 + ["UMD", "ST_Rev"],
}
PRIMARY_SPEC = "ff5_umd"


def load_factors(ff5: pd.DataFrame, umd: pd.DataFrame, strev: pd.DataFrame) -> pd.DataFrame:
    """Merge Ken French factor tables (decimal returns) on month-end date.

    Renames the momentum column to UMD and the reversal column to ST_Rev
    whatever their source spelling. Output columns: date, FF5..., RF, UMD,
    ST_Rev. Rows missing any factor are kept (regressions drop them per spec).
    """
    def tidy(frame, pattern, name):
        frame = frame.copy()
        frame["date"] = to_month_end(frame["date"])
        match = [c for c in frame.columns if c != "date" and re.search(pattern, str(c), re.I)]
        if len(match) != 1:
            raise ValueError(f"cannot find a unique {name} column in {list(frame.columns)}")
        return frame[["date", match[0]]].rename(columns={match[0]: name})

    base = ff5.copy()
    base["date"] = to_month_end(base["date"])
    missing = [c for c in FF5 if c not in base.columns]
    if missing:
        raise ValueError(f"FF5 file is missing {missing}")
    out = base[["date"] + FF5 + [c for c in ["RF"] if c in base.columns]]
    out = out.merge(tidy(umd, r"umd|mom", "UMD"), on="date", how="outer")
    out = out.merge(tidy(strev, r"st.?rev", "ST_Rev"), on="date", how="outer")
    return out.sort_values("date").reset_index(drop=True)


def align(strategy_rows: pd.DataFrame, factors: pd.DataFrame) -> pd.DataFrame:
    """Attach same-month factor returns to strategy returns.

    Input rows need `return_month`. Raises if any return month with a
    realized return is absent from the factor dates (CLAUDE.md 9 acceptance:
    no off-by-one and no silently dropped months).
    """
    # Renumber rows: callers pass filtered subsets, and merge() renumbers its
    # output, so a label-based mask from the input would not line up.
    rows = strategy_rows.reset_index(drop=True).copy()
    rows["return_month"] = to_month_end(rows["return_month"])
    realized = rows["gross_return"].notna().to_numpy()
    absent = set(rows.loc[realized, "return_month"]) - set(factors["date"])
    if absent:
        raise ValueError(f"factor data missing for return months: {sorted(absent)[:5]}...")
    merged = rows.merge(factors, left_on="return_month", right_on="date",
                        how="left", validate="many_to_one")
    matched = merged["date"].to_numpy()[realized] == merged["return_month"].to_numpy()[realized]
    if not matched.all():
        raise ValueError("strategy and factor months are misaligned")
    return merged


def nw_regression(y: pd.Series, x: pd.DataFrame, lags: int = config.NW_LAGS) -> dict:
    """OLS of y on a constant and x with Newey-West (HAC) standard errors.

    Output: n, alpha_monthly, alpha_ann (x12), alpha_t, r2, and beta_/t_ for
    each regressor. All NaN when there are not more observations than
    parameters + 1.
    """
    import statsmodels.api as sm

    data = pd.concat([y.rename("y"), x], axis=1).dropna()
    k = x.shape[1] + 1
    out = {"n": len(data)}
    if len(data) <= k + 1:
        out.update({"alpha_monthly": np.nan, "alpha_ann": np.nan, "alpha_t": np.nan,
                    "r2": np.nan})
        for c in x.columns:
            out[f"beta_{c}"], out[f"t_{c}"] = np.nan, np.nan
        return out
    fit = sm.OLS(data["y"], sm.add_constant(data[x.columns])).fit(
        cov_type="HAC", cov_kwds={"maxlags": lags})
    out.update({"alpha_monthly": fit.params["const"],
                "alpha_ann": fit.params["const"] * config.ANNUALIZE,
                "alpha_t": fit.tvalues["const"], "r2": fit.rsquared})
    for c in x.columns:
        out[f"beta_{c}"], out[f"t_{c}"] = fit.params[c], fit.tvalues[c]
    return out


def factor_regressions(results: pd.DataFrame, factors: pd.DataFrame,
                       return_col: str = f"net_return_{config.BASE_COST_BPS}bps"
                       ) -> pd.DataFrame:
    """Run every spec for every strategy, method, and window.

    Input: Phase 6 `strategy_returns_by_month` rows and the merged factors.
    Output: one row per (strategy, method, window, spec) with alpha, its
    Newey-West t-stat, loadings with t-stats, R^2, and sample months.
    """
    merged = align(results, factors)
    merged["month"] = to_month_end(merged["month"])
    bounds = window_bounds(merged, merged["month"].max())
    rows = []
    for (strategy, method), g in merged.groupby(["strategy", "method"], sort=False):
        windows = {"full": g}
        windows.update({name: g.loc[g["month"].between(*b)] for name, b in bounds.items()})
        for window, w in windows.items():
            for spec, cols in SPECS.items():
                stats = nw_regression(w[return_col], w[cols])
                rows.append({"strategy": strategy, "method": method, "window": window,
                             "spec": spec, "return_series": return_col,
                             "first_return_month": w.loc[w[return_col].notna(),
                                                         "return_month"].min(),
                             "last_return_month": w.loc[w[return_col].notna(),
                                                        "return_month"].max(),
                             **stats})
    return pd.DataFrame(rows)


def umd_comparison(regressions: pd.DataFrame, method: str = "mv") -> pd.DataFrame:
    """Key table: alpha with vs. without UMD, plus the rejection-criterion check.

    `passes_criterion` is "yes" only when the 6-factor (FF5 + UMD) net alpha
    is positive with Newey-West t >= 2 (CLAUDE.md 0). Windows with fewer than
    config.CRITERION_MIN_MONTHS months read "low power" (e.g. the recent 18
    months: 10-17 observations for 7 parameters and 6 Newey-West lags).
    """
    reg = regressions.loc[regressions["method"].eq(method)]
    keys = ["strategy", "window"]
    with_umd = reg.loc[reg["spec"].eq("ff5_umd"),
                       keys + ["n", "alpha_ann", "alpha_t", "beta_UMD", "t_UMD", "r2"]]
    without = reg.loc[reg["spec"].eq("ff5"), keys + ["alpha_ann", "alpha_t", "r2"]]
    out = with_umd.merge(without, on=keys, suffixes=("_ff5_umd", "_ff5"))
    out = out.rename(columns={"n": "months", "beta_UMD": "beta_UMD_ff5_umd",
                              "t_UMD": "t_UMD_ff5_umd"})
    passes = (out["alpha_t_ff5_umd"] >= 2) & (out["alpha_ann_ff5_umd"] > 0)
    out["passes_criterion"] = np.select(
        [out["months"] < config.CRITERION_MIN_MONTHS, out["alpha_t_ff5_umd"].isna(), passes],
        ["low power", "n/a", "yes"], default="no")
    return out


def main() -> None:
    """Load Phase 6 returns and Ken French factors, run and save Phase 7."""
    raw = config.DATA_RAW
    paths = {n: raw / f"{n}.parquet" for n in ("kf_ff5", "kf_umd", "kf_strev")}
    missing = [str(p) for p in paths.values() if not p.exists()]
    if missing:
        raise FileNotFoundError("Missing factor files (run src.pull_public): "
                                + ", ".join(missing))
    factors = load_factors(*(pd.read_parquet(p) for p in paths.values()))
    results = pd.read_csv(config.TABLES / "strategy_returns_by_month.csv",
                          parse_dates=["month", "return_month"])
    regressions = factor_regressions(results, factors)
    comparison = umd_comparison(regressions)
    config.TABLES.mkdir(parents=True, exist_ok=True)
    regressions.to_csv(config.TABLES / "factor_regressions.csv", index=False)
    comparison.to_csv(config.TABLES / "alpha_with_without_umd.csv", index=False)
    pd.set_option("display.width", 200)
    print(comparison.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    primary = comparison.loc[comparison["window"].isin(["common", "post_2010"])]
    print("\nRejection criterion (6-factor net alpha t >= 2, mean-variance books):")
    for _, r in primary.iterrows():
        verdict = {"yes": "passes", "no": "fails"}.get(r["passes_criterion"],
                                                       r["passes_criterion"])
        print(f"  {r['strategy']:9s} {r['window']:10s} alpha {r['alpha_ann_ff5_umd']:+.2%}/yr "
              f"t {r['alpha_t_ff5_umd']:+.2f} -> {verdict}")


if __name__ == "__main__":
    main()
