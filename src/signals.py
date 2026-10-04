"""Construct value-weighted industry momentum and I/B/E/S revision signals."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src.utils import to_month_end  # noqa: E402


def momentum_signal(returns: pd.DataFrame, lookback: int = config.MOM_LOOKBACK,
                    skip: int = config.MOM_SKIP) -> pd.DataFrame:
    """Compute 12-1 style compounded momentum by industry (CLAUDE.md 5.1).

    Input is a month-end wide industry-return panel. For lookback 12 and skip
    1, the signal at month-end t compounds the 11 returns of months t-11
    through t-1, skipping the most recent month t. Output has month,
    industry, and mom columns.
    """
    if lookback <= skip:
        raise ValueError("lookback must exceed skip")
    frame = returns.copy()
    frame["date"] = to_month_end(frame["date"])
    frame = frame.sort_values("date").set_index("date")
    industries = [col for col in frame.columns if col != "date"]
    period_count = lookback - skip
    lag = skip
    compounded = (frame[industries].add(1).shift(lag)
                  .rolling(period_count, min_periods=period_count)
                  .apply(np.prod, raw=True).sub(1))
    return (compounded.rename_axis("month").reset_index()
            .melt(id_vars="month", var_name="industry", value_name="mom"))


def industry_returns_long(returns: pd.DataFrame, sic_ranges: pd.DataFrame,
                          other_industry: int = config.OTHER_INDUSTRY_49
                          ) -> pd.DataFrame:
    """Convert Ken French named industry columns to numeric industry IDs."""
    names = (sic_ranges[["industry", "short"]].drop_duplicates()
             .assign(short=lambda frame: frame["short"].astype(str).str.strip()))
    by_name = dict(zip(names["short"], names["industry"].astype(int)))
    by_name["Other"] = other_industry
    frame = returns.copy()
    frame["date"] = to_month_end(frame["date"])
    cols = [col for col in frame.columns if col != "date"]
    normalized = {str(col).strip(): col for col in cols}
    missing = sorted(set(by_name) - set(normalized))
    if missing:
        raise ValueError(f"industry return columns missing from Ken French data: {missing}")
    selected = frame[["date"] + [normalized[name] for name in by_name]]
    result = selected.melt(id_vars="date", var_name="industry_name", value_name="ret")
    result["industry"] = result["industry_name"].astype(str).str.strip().map(by_name)
    result["ret"] = pd.to_numeric(result["ret"], errors="coerce")
    return result.drop(columns="industry_name").rename(columns={"date": "month"})


def industry_revisions(ibes: pd.DataFrame, min_analysts: int = config.MIN_ANALYSTS,
                       min_firms: int = config.MIN_FIRMS_PER_INDUSTRY
                       ) -> pd.DataFrame:
    """Aggregate main and alternative revision measures by month and industry.

    Main REV is the market-cap-weighted net-revision ratio. Alternative REV is
    the same-period three-month consensus change scaled by absolute price,
    winsorized cross-sectionally each month before value-weighted aggregation.
    """
    frame = ibes.copy()
    frame["month"] = to_month_end(frame["month"])
    frame["industry"] = pd.to_numeric(frame["industry"], errors="coerce")
    frame["fpedats"] = pd.to_datetime(frame["fpedats"], errors="coerce")
    for col in ("numest", "numup", "numdown", "meanest", "mktcap", "prc"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.sort_values(["permno", "fpedats", "month"])
    prior = frame[["permno", "fpedats", "month", "meanest", "numest"]].copy()
    prior["month"] = prior["month"] + pd.offsets.MonthEnd(config.REV_ALT_LAG_MONTHS)
    prior = prior.rename(columns={"meanest": "meanest_lag", "numest": "numest_lag"})
    frame = frame.drop(columns=[c for c in frame.columns if c.startswith("meanest_lag")], errors="ignore")
    frame = frame.merge(prior, on=["permno", "fpedats", "month"], how="left",
                        validate="many_to_one")

    valid = (frame["numest"].ge(min_analysts) & frame["mktcap"].gt(0)
             & frame["industry"].notna())
    frame["rev_firm"] = ((frame["numup"] - frame["numdown"]) / frame["numest"])
    frame.loc[~valid, "rev_firm"] = np.nan
    frame["rev_alt_firm"] = ((frame["meanest"] - frame["meanest_lag"])
                             / frame["prc"].abs())
    frame.loc[~valid | frame["numest_lag"].lt(min_analysts)
              | frame["prc"].isna() | frame["prc"].eq(0), "rev_alt_firm"] = np.nan

    quantiles = (frame.groupby("month")["rev_alt_firm"]
                 .quantile(list(config.REV_ALT_WINSOR)).unstack())
    if not quantiles.empty:
        frame["rev_alt_firm"] = frame["rev_alt_firm"].clip(
            lower=frame["month"].map(quantiles[config.REV_ALT_WINSOR[0]]),
            upper=frame["month"].map(quantiles[config.REV_ALT_WINSOR[1]]))

    def aggregate(column: str, label: str) -> pd.DataFrame:
        usable = frame.loc[frame[column].notna()].copy()
        usable["weighted_value"] = usable[column] * usable["mktcap"]
        grouped = (usable.groupby(["month", "industry"], as_index=False)
                   .agg(weighted_value=("weighted_value", "sum"),
                        total_cap=("mktcap", "sum"),
                        firms=("permno", "nunique")))
        grouped[label] = grouped["weighted_value"] / grouped["total_cap"]
        grouped.loc[grouped["firms"] < min_firms, label] = np.nan
        return grouped[["month", "industry", label, "firms"]]

    main = aggregate("rev_firm", "rev")
    alt = aggregate("rev_alt_firm", "rev_alt").rename(columns={"firms": "rev_alt_firms"})
    result = main.merge(alt, on=["month", "industry"], how="outer")
    return result.rename(columns={"firms": "rev_firms"})


def _zscore(values: pd.Series, winsor: float) -> pd.Series:
    """Cross-sectionally standardize values while preserving missing observations."""
    available = values.notna()
    standardized = pd.Series(np.nan, index=values.index, dtype="float64")
    if not available.any():
        return standardized
    scale = values.loc[available].std(ddof=0)
    if pd.isna(scale) or scale == 0:
        standardized.loc[available] = 0.0
        return standardized
    standardized.loc[available] = (
        (values.loc[available] - values.loc[available].mean()) / scale
    ).clip(-winsor, winsor)
    return standardized


def attach_next_month_returns(signals: pd.DataFrame,
                              returns_long: pd.DataFrame) -> pd.DataFrame:
    """Attach return in calendar month t+1 to signals formed at month-end t."""
    future = returns_long[["month", "industry", "ret"]].copy()
    future["month"] = to_month_end(future["month"] - pd.offsets.MonthEnd(1))
    future = future.rename(columns={"ret": "next_return"})
    return signals.merge(future, on=["month", "industry"], how="left", validate="one_to_one")


def build_signals(ibes: pd.DataFrame, industry_returns: pd.DataFrame,
                  sic_ranges: pd.DataFrame, lookback: int = config.MOM_LOOKBACK,
                  skip: int = config.MOM_SKIP,
                  min_analysts: int = config.MIN_ANALYSTS,
                  min_firms: int = config.MIN_FIRMS_PER_INDUSTRY,
                  other_industry: int = config.OTHER_INDUSTRY_49) -> pd.DataFrame:
    """Build the full industry signal panel with one-month-ahead returns.

    Output: one row per (month, industry) with raw and z-scored signals formed
    at month-end t and `next_return`, the industry return in month t+1.
    Signals without data stay missing; no months are dropped.
    `other_industry` is the ID of "Other" (49 for the 49-industry set, 30 for
    the 30-industry robustness set).
    """
    returns_long = industry_returns_long(industry_returns, sic_ranges, other_industry)
    momentum = momentum_signal(industry_returns, lookback, skip)
    revisions = industry_revisions(ibes, min_analysts, min_firms)

    names = (sic_ranges[["industry", "short"]].drop_duplicates()
             .assign(short=lambda frame: frame["short"].astype(str).str.strip()))
    by_name = dict(zip(names["short"], names["industry"].astype(int)))
    by_name["Other"] = other_industry
    momentum["industry"] = (momentum["industry"].astype(str).str.strip()
                            .map(by_name).astype("Int64"))
    revisions["industry"] = pd.to_numeric(revisions["industry"]).astype("Int64")
    panel = momentum.merge(revisions, on=["month", "industry"], how="left")
    panel = panel.sort_values(["month", "industry"])
    for signal in ("mom", "rev", "rev_alt"):
        panel[f"{signal}_z"] = panel.groupby("month")[signal].transform(
            lambda values: _zscore(values, config.Z_WINSOR))
    return attach_next_month_returns(panel, returns_long)


SIGNALS = ("mom", "rev", "rev_alt")


def signal_coverage(signal: pd.DataFrame) -> pd.DataFrame:
    """Report available and missing industries for each signal month.

    Output: one row per month with industries, <name>_available and
    <name>_missing for mom, rev, rev_alt, and next_return.
    """
    coverage = (signal.groupby("month", as_index=False)
                .agg(industries=("industry", "nunique"),
                     mom_available=("mom", "count"),
                     rev_available=("rev", "count"),
                     rev_alt_available=("rev_alt", "count"),
                     next_return_available=("next_return", "count")))
    for name in ("mom", "rev", "rev_alt", "next_return"):
        coverage[f"{name}_missing"] = coverage["industries"] - coverage[f"{name}_available"]
    return coverage


def signal_summary(panel: pd.DataFrame) -> pd.DataFrame:
    """Summary of each z-scored signal over months where it exists at all.

    Output columns: mean, std, min, max of the z-score, months with any
    coverage, and average share of the 49 industries covered in those months.
    """
    rows = []
    for s in SIGNALS:
        z = panel[f"{s}_z"]
        by_month = panel.assign(has=z.notna()).groupby("month")["has"].mean()
        active = by_month[by_month > 0]
        rows.append({
            "signal": f"{s}_z", "mean_z": z.mean(), "std_z": z.std(),
            "min_z": z.min(), "max_z": z.max(),
            "first_month": active.index.min(), "last_month": active.index.max(),
            "months_covered": len(active),
            "avg_industry_coverage_frac": active.mean(),
        })
    return pd.DataFrame(rows)


def horizon_coverage(panel: pd.DataFrame) -> pd.DataFrame:
    """How much of each planned review window each signal actually covers.

    Windows (CLAUDE.md 10.1): full sample, post-2010, and the last
    config.RECENT_MONTHS signal months of the panel (not shifted to where data
    is complete). For each window and signal reports: months in the window,
    months with the signal for >= 1 industry, months that are also evaluable
    (signal and next_return both present), and industry-months with the signal.
    """
    last = panel["month"].max()
    recent_start = last - pd.offsets.MonthEnd(config.RECENT_MONTHS - 1)
    windows = {
        "full": (panel["month"].min(), last),
        "post_2010": (pd.Timestamp(config.POST_SPLIT), last),
        f"recent_{config.RECENT_MONTHS}m": (recent_start, last),
    }
    rows = []
    for label, (start, end) in windows.items():
        w = panel.loc[panel["month"].between(start, end)]
        for s in SIGNALS:
            has = w[f"{s}_z"].notna()
            evaluable = has & w["next_return"].notna()
            rows.append({
                "window": label, "start": start, "end": end, "signal": s,
                "window_months": w["month"].nunique(),
                "months_with_signal": w.loc[has, "month"].nunique(),
                "months_evaluable": w.loc[evaluable, "month"].nunique(),
                "industry_months_with_signal": int(has.sum()),
            })
    return pd.DataFrame(rows)


def mom_rev_cross_sectional_corr(panel: pd.DataFrame) -> pd.DataFrame:
    """Monthly Pearson correlation of mom_z and rev_z across industries.

    Uses industries where both are present; months with fewer than 3 such
    industries are dropped. Output: month, corr, and its rolling mean over
    config.ROLLING_CORR_MONTHS months.
    """
    both = panel.dropna(subset=["mom_z", "rev_z"])
    counts = both.groupby("month")["industry"].size()
    corr = (both.groupby("month")[["mom_z", "rev_z"]]
            .apply(lambda g: g["mom_z"].corr(g["rev_z"])))
    corr = corr[counts.reindex(corr.index).ge(3)].rename("corr").to_frame()
    corr["corr_rolling"] = corr["corr"].rolling(config.ROLLING_CORR_MONTHS).mean()
    return corr.reset_index()


def plot_mom_rev_corr(corr: pd.DataFrame, path: Path) -> Path:
    """Line chart of the monthly MOM-REV correlation and its rolling mean."""
    from src import plots

    fig, ax = plots.new_figure()
    ax.plot(corr["month"], corr["corr"], color=plots.SERIES[0], linewidth=1.0,
            alpha=0.55, label="Monthly")
    ax.plot(corr["month"], corr["corr_rolling"], color=plots.SERIES[1], linewidth=2.0,
            label=f"{config.ROLLING_CORR_MONTHS}-month rolling mean")
    ax.axhline(0, color=plots.BASELINE, linewidth=1.0)
    ax.set_ylim(-1, 1)
    start, end = corr["month"].min(), corr["month"].max()
    return plots.finish(
        fig, ax,
        title=f"Cross-sectional correlation of industry MOM and REV z-scores, "
              f"{start:%b %Y}–{end:%b %Y}",
        xlabel="Signal month (month-end)",
        ylabel="Pearson correlation across industries (unitless)",
        path=path)


def main() -> None:
    """Build and save the processed signal panel plus Phase 3 tables and figure."""
    signal = build_signals(
        pd.read_parquet(config.DATA_INTERIM / "ibes_crsp_monthly.parquet"),
        pd.read_parquet(config.DATA_RAW / "kf_ind49_vw.parquet"),
        pd.read_parquet(config.DATA_RAW / "kf_sic49.parquet"),
    )
    config.DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    signal.to_parquet(config.DATA_PROCESSED / "signals.parquet", compression="zstd", index=False)
    config.TABLES.mkdir(parents=True, exist_ok=True)
    summary = signal_summary(signal)
    summary.to_csv(config.TABLES / "signal_summary.csv", index=False)
    signal_coverage(signal).to_csv(config.TABLES / "signal_coverage_by_month.csv", index=False)
    horizons = horizon_coverage(signal)
    horizons.to_csv(config.TABLES / "signal_coverage_by_horizon.csv", index=False)
    print(horizons.to_string(index=False))
    corr = mom_rev_cross_sectional_corr(signal)
    corr.to_csv(config.TABLES / "mom_rev_xs_corr_by_month.csv", index=False)
    plot_mom_rev_corr(corr, config.FIGURES / "mom_rev_correlation.png")
    print(summary.to_string(index=False))
    print(f"mean monthly MOM-REV correlation: {corr['corr'].mean():.3f}")
    print(f"signals: {len(signal):,} industry-months through {signal['month'].max():%Y-%m}")


if __name__ == "__main__":
    main()