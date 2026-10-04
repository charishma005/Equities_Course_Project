"""Phase 4: information coefficients, REV orthogonalization, and blending."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src.signals import _zscore  # noqa: E402
from src.utils import to_month_end  # noqa: E402

SIGNAL_COLUMNS = {
    "mom": "mom_z",
    "rev": "rev_z",
    "rev_alt": "rev_alt_z",
    "rev_orth": "rev_orth_z",
    "blend": "blend_z",
}


def orthogonalize_revision(panel: pd.DataFrame,
                           min_industries: int = config.IC_MIN_INDUSTRIES
                           ) -> pd.DataFrame:
    """Regress REV z-scores on MOM z-scores cross-sectionally each month.

    Output adds `rev_orth_z`, the OLS residual for industries where both
    signals are present. The regression uses signals only, never future returns.
    """
    result = panel.copy()
    result["rev_orth_z"] = np.nan
    for _, group in result.groupby("month", sort=False):
        valid = group[["mom_z", "rev_z"]].dropna()
        if len(valid) < min_industries:
            continue
        design = np.column_stack([np.ones(len(valid)), valid["mom_z"].to_numpy()])
        coefficients = np.linalg.lstsq(design, valid["rev_z"].to_numpy(), rcond=None)[0]
        residual = valid["rev_z"].to_numpy() - design @ coefficients
        result.loc[valid.index, "rev_orth_z"] = residual
    return result


def monthly_information_coefficients(
    panel: pd.DataFrame,
    score_columns: dict[str, str] | None = None,
    min_industries: int = config.IC_MIN_INDUSTRIES,
) -> pd.DataFrame:
    """Compute monthly Pearson and Spearman ICs against next-month returns.

    IC rows are dated by the signal month t and compare its cross-section to
    `next_return` in t+1. A month needs at least `min_industries` valid pairs.
    """
    score_columns = SIGNAL_COLUMNS if score_columns is None else score_columns
    rows = []
    for month, group in panel.groupby("month", sort=True):
        for signal, column in score_columns.items():
            if column not in group:
                continue
            available = group[column].notna()
            pairs = group.loc[available, [column, "next_return"]].dropna()
            pearson_ic = np.nan
            spearman_ic = np.nan
            if len(pairs) >= min_industries:
                x = pairs[column].to_numpy(dtype=float)
                y = pairs["next_return"].to_numpy(dtype=float)
                if np.std(x) > 0 and np.std(y) > 0:
                    pearson_ic = float(stats.pearsonr(x, y).statistic)
                    spearman_ic = float(stats.spearmanr(x, y).statistic)
            rows.append({
                "month": month,
                "signal": signal,
                "signal_industries": int(available.sum()),
                "n_industries": len(pairs),
                "pearson_ic": pearson_ic,
                "spearman_ic": spearman_ic,
            })
    return pd.DataFrame(rows)


def expanding_blend_weights(
    panel: pd.DataFrame,
    monthly_ic: pd.DataFrame,
    min_history: int = config.BLEND_MIN_MONTHS,
) -> pd.DataFrame:
    """Estimate month-t blend weights using only outcomes known by month t.

    IC history and the cross-signal correlation matrix use signal months
    strictly before t. This admits the t-1 signal's t+1 return, observable by
    month t, but never uses a same-month or future outcome.
    """
    panel = panel.copy()
    panel["month"] = to_month_end(panel["month"])
    monthly_ic = monthly_ic.copy()
    monthly_ic["month"] = to_month_end(monthly_ic["month"])
    ic_pair = (monthly_ic.loc[monthly_ic["signal"].isin(["mom", "rev"])]
               .pivot(index="month", columns="signal", values="spearman_ic")
               .reindex(columns=["mom", "rev"]))
    rows = []
    for month in sorted(panel["month"].dropna().unique()):
        history = ic_pair.loc[ic_pair.index < month].dropna(subset=["mom", "rev"])
        weights = np.array([np.nan, np.nan])
        mean_ic = np.array([np.nan, np.nan])
        signal_corr = np.nan
        if len(history) >= min_history:
            prior_scores = panel.loc[
                panel["month"].lt(month), ["mom_z", "rev_z"]
            ].dropna()
            if len(prior_scores) >= 2:
                correlation = prior_scores.corr().to_numpy(dtype=float)
                mean_ic = history[["mom", "rev"]].mean().to_numpy(dtype=float)
                if np.isfinite(correlation).all() and np.isfinite(mean_ic).all():
                    raw_weights = np.linalg.pinv(correlation) @ mean_ic
                    denominator = raw_weights.sum()
                    if np.isfinite(denominator) and abs(denominator) > 1e-12:
                        weights = raw_weights / denominator
                        signal_corr = correlation[0, 1]
        rows.append({
            "month": month,
            "history_ic_months": len(history),
            "mean_mom_ic": mean_ic[0],
            "mean_rev_ic": mean_ic[1],
            "signal_corr": signal_corr,
            "mom_weight": weights[0],
            "rev_weight": weights[1],
        })
    return pd.DataFrame(rows)


def apply_expanding_blend(
    panel: pd.DataFrame,
    monthly_ic: pd.DataFrame,
    min_history: int = config.BLEND_MIN_MONTHS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Attach expanding weights and a blended z-score requiring both inputs."""
    result = panel.copy()
    result["month"] = to_month_end(result["month"])
    weights = expanding_blend_weights(result, monthly_ic, min_history)
    result = result.merge(weights, on="month", how="left", validate="many_to_one")
    result["blend_raw"] = (
        result["mom_weight"] * result["mom_z"]
        + result["rev_weight"] * result["rev_z"]
    )
    complete = result["mom_z"].notna() & result["rev_z"].notna()
    result.loc[~complete, "blend_raw"] = np.nan
    result["blend_z"] = result.groupby("month")["blend_raw"].transform(
        lambda values: _zscore(values, config.Z_WINSOR))
    return result, weights


def _mean_tstat(values: pd.Series) -> float:
    values = values.dropna()
    if len(values) < 2:
        return np.nan
    standard_error = values.std(ddof=1) / np.sqrt(len(values))
    return float(values.mean() / standard_error) if standard_error > 0 else np.nan


def _mean_tstat_nw(values: pd.Series, lags: int = config.NW_LAGS) -> float:
    """t-stat of the mean with Newey-West (HAC) standard errors.

    Monthly ICs can be autocorrelated, which the plain t-stat ignores.
    Returns NaN with fewer than lags + 2 observations.
    """
    import statsmodels.api as sm

    values = values.dropna().to_numpy(dtype=float)
    if len(values) < lags + 2 or np.std(values) == 0:
        return np.nan
    fit = sm.OLS(values, np.ones(len(values))).fit(
        cov_type="HAC", cov_kwds={"maxlags": lags})
    return float(fit.tvalues[0])


def summarize_ic_by_horizon(
    panel: pd.DataFrame,
    monthly_ic: pd.DataFrame,
    recent_months: int = config.RECENT_MONTHS,
) -> pd.DataFrame:
    """Summarize IC magnitude, significance, and actual coverage by planned window.

    Windows: full (first to last panel month), rev_sample (first to last month
    with any REV z-score, so MOM and REV are compared over the same months),
    post_2010, and the last `recent_months` signal months (not shifted).
    t-stats are reported both plain and Newey-West (config.NW_LAGS lags).
    """
    panel = panel.copy()
    panel["month"] = to_month_end(panel["month"])
    monthly_ic = monthly_ic.copy()
    monthly_ic["month"] = to_month_end(monthly_ic["month"])
    first, last = panel["month"].min(), panel["month"].max()
    rev_months = panel.loc[panel["rev_z"].notna(), "month"]
    recent_start = last - pd.offsets.MonthEnd(recent_months - 1)
    windows = {
        "full": (first, last),
        "rev_sample": (rev_months.min(), rev_months.max()),
        "post_2010": (pd.Timestamp(config.POST_SPLIT), last),
        f"recent_{recent_months}m": (recent_start, last),
    }
    rows = []
    for window, (start, end) in windows.items():
        window_panel = panel.loc[panel["month"].between(start, end)]
        window_ic = monthly_ic.loc[monthly_ic["month"].between(start, end)]
        for signal, column in SIGNAL_COLUMNS.items():
            signal_rows = window_ic.loc[window_ic["signal"].eq(signal)]
            valid = signal_rows.dropna(subset=["spearman_ic"])
            pearson = valid["pearson_ic"].dropna()
            spearman = valid["spearman_ic"].dropna()
            available = window_panel.loc[window_panel[column].notna()]
            rows.append({
                "window": window,
                "window_start": start,
                "window_end": end,
                "signal": signal,
                "window_months": window_panel["month"].nunique(),
                "months_with_signal": available["month"].nunique(),
                "industry_months_with_signal": len(available),
                "ic_months": len(valid),
                "industry_month_pairs": int(valid["n_industries"].sum()),
                "pearson_mean": pearson.mean(),
                "pearson_std": pearson.std(ddof=1),
                "pearson_tstat": _mean_tstat(pearson),
                "pearson_tstat_nw": _mean_tstat_nw(pearson),
                "pearson_ir": pearson.mean() / pearson.std(ddof=1)
                if pearson.std(ddof=1) > 0 else np.nan,
                "pearson_positive_pct": 100 * pearson.gt(0).mean(),
                "spearman_mean": spearman.mean(),
                "spearman_std": spearman.std(ddof=1),
                "spearman_tstat": _mean_tstat(spearman),
                "spearman_tstat_nw": _mean_tstat_nw(spearman),
                "spearman_ir": spearman.mean() / spearman.std(ddof=1)
                if spearman.std(ddof=1) > 0 else np.nan,
                "spearman_positive_pct": 100 * spearman.gt(0).mean(),
            })
    return pd.DataFrame(rows)


def _plot_rolling_ic(monthly_ic: pd.DataFrame) -> Path:
    from src import plots

    figure, axis = plots.new_figure()
    plotted = []
    for signal, color, label in (("mom", plots.SERIES[0], "MOM"),
                                 ("rev", plots.SERIES[1], "REV")):
        series = (monthly_ic.loc[monthly_ic["signal"].eq(signal)]
                  .set_index("month")["spearman_ic"].sort_index())
        rolling = series.rolling(config.ROLLING_IC_MONTHS,
                                 min_periods=config.ROLLING_IC_MONTHS).mean()
        axis.plot(rolling.index, rolling, color=color, linewidth=1.8, label=label)
        plotted.append(rolling.dropna())
    axis.axhline(0, color=plots.BASELINE, linewidth=1.0)
    span = pd.concat(plotted)
    return plots.finish(
        figure, axis,
        title=f"Rolling {config.ROLLING_IC_MONTHS}-month Spearman IC: MOM and REV, "
              f"{span.index.min():%b %Y}–{span.index.max():%b %Y}",
        xlabel="Signal month (month-end)",
        ylabel="Mean monthly Spearman IC (unitless)",
        path=config.FIGURES / "rolling_ic_mom_rev.png",
    )


def _plot_blend_weights(weights: pd.DataFrame) -> Path:
    from src import plots

    figure, axis = plots.new_figure()
    shown = weights.dropna(subset=["mom_weight"])
    axis.plot(weights["month"], weights["mom_weight"],
              color=plots.SERIES[0], linewidth=1.8, label="MOM weight")
    axis.plot(weights["month"], weights["rev_weight"],
              color=plots.SERIES[1], linewidth=1.8, label="REV weight")
    axis.axhline(0, color=plots.BASELINE, linewidth=1.0)
    return plots.finish(
        figure, axis,
        f"Expanding-window blend weights, {shown['month'].min():%b %Y}–"
        f"{shown['month'].max():%b %Y}",
        "Signal month (month-end)", "Weight (unitless)",
        config.FIGURES / "blend_weights.png",
    )


def run_phase4(panel: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Run primary-sample IC, orthogonal REV, coverage summaries, and blend."""
    panel = panel.copy()
    panel["month"] = to_month_end(panel["month"])
    panel = orthogonalize_revision(panel)
    initial_ic = monthly_information_coefficients(panel)
    blended, weights = apply_expanding_blend(panel, initial_ic)
    monthly_ic = monthly_information_coefficients(blended)
    summary = summarize_ic_by_horizon(blended, monthly_ic)
    return {
        "panel": blended,
        "monthly_ic": monthly_ic,
        "summary": summary,
        "weights": weights,
    }


def main() -> None:
    """Run Phase 4 on primary signals and save tables and figures."""
    signal_path = config.DATA_PROCESSED / "signals.parquet"
    if not signal_path.exists():
        raise FileNotFoundError(f"Missing primary signal panel: {signal_path}")
    result = run_phase4(pd.read_parquet(signal_path))
    config.TABLES.mkdir(parents=True, exist_ok=True)
    config.DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    result["monthly_ic"].to_csv(config.TABLES / "ic_by_month.csv", index=False)
    result["summary"].to_csv(config.TABLES / "ic_summary_by_horizon.csv", index=False)
    result["weights"].to_csv(config.TABLES / "blend_weights_by_month.csv", index=False)
    result["panel"].to_parquet(
        config.DATA_PROCESSED / "signals_phase4.parquet",
        compression="zstd", index=False)
    _plot_rolling_ic(result["monthly_ic"])
    _plot_blend_weights(result["weights"])
    print(result["summary"].to_string(index=False))
    print("\nLatest blend weights:")
    print(result["weights"].tail(12).to_string(index=False))


if __name__ == "__main__":
    main()