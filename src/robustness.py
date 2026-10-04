"""Phase 8: robustness grid and subperiod stability (CLAUDE.md 10).

Grid design: one-at-a-time. Each row changes one dimension of
config.GRID_BASE and reruns the blended strategy end to end: signals ->
Phase 4 IC and expanding blend -> Phase 5 mean-variance holdings -> Phase 6
backtest. A full factorial grid would be ~1,900 runs. The momentum-lookback
x covariance-half-life heatmap is a full 3x3. Cost rows reuse the base run's
10/20/30 bp net returns. Every row is scored on the same formation months
(config.ROBUSTNESS_WINDOW).

Inputs: the committed Phase 4 panel. Rows that need raw data (minimum
analysts per firm, the 30-industry set) run only when data/interim and
data/raw files exist; otherwise they are listed as skipped. Factor alphas and
the rolling alpha need the Ken French factor files in data/raw.

Usage:
    python -m src.robustness              # grid + stability outputs
    python -m src.robustness --alphas-only  # add factor alphas to saved runs
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src import attribution, backtest, ic, portfolio, risk, signals  # noqa: E402
from src.utils import to_month_end  # noqa: E402

PHASE3_COLUMNS = ["month", "industry", "mom", "rev", "rev_firms", "rev_alt",
                  "rev_alt_firms", "mom_z", "rev_z", "rev_alt_z", "next_return"]
NEEDS_RAW = {"min_analysts", "industry_set"}


# --------------------------------------------------------------------------
# Variant definitions
# --------------------------------------------------------------------------
def grid_variants() -> list[dict]:
    """One-at-a-time rows plus the extra heatmap cells, base first.

    Each variant: id, dimension, value, and a full settings dict.
    """
    base = dict(config.GRID_BASE)
    variants = [{"id": "base", "dimension": "base", "value": "base", **base}]
    for dim, values in config.GRID.items():
        if dim == "cost_bps":
            continue
        for value in values:
            if value == base[dim]:
                continue
            variants.append({"id": f"{dim}={value}", "dimension": dim, "value": value,
                             **{**base, dim: value}})
    for lookback in config.GRID["mom_lookback"]:
        for halflife in config.GRID["cov_halflife"]:
            if lookback == base["mom_lookback"] or halflife == base["cov_halflife"]:
                continue        # already a one-at-a-time row or the base
            variants.append({"id": f"heatmap:mom_lookback={lookback},cov_halflife={halflife}",
                             "dimension": "heatmap", "value": f"{lookback}x{halflife}",
                             **{**base, "mom_lookback": lookback, "cov_halflife": halflife}})
    return variants


# --------------------------------------------------------------------------
# Building a variant's signal panel
# --------------------------------------------------------------------------
def with_momentum_lookback(panel: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """Replace mom/mom_z with momentum over `lookback` months (skip MOM_SKIP),
    computed from industry returns rebuilt from `next_return`.

    Uses returns through t-1 only, like signals.momentum_signal.
    """
    returns = risk.returns_from_signal_panel(panel)
    wide = returns.reset_index().rename(columns={"month": "date"})
    mom = signals.momentum_signal(wide, lookback=lookback, skip=config.MOM_SKIP)
    mom["industry"] = pd.to_numeric(mom["industry"]).astype(int)
    out = panel.drop(columns=["mom", "mom_z"]).merge(mom, on=["month", "industry"],
                                                     how="left")
    out["mom_z"] = out.groupby("month")["mom"].transform(
        lambda v: signals._zscore(v, config.Z_WINSOR))
    return out


def remap_to_30_industries(ibes: pd.DataFrame, crsp_monthly: pd.DataFrame,
                           sic30: pd.DataFrame) -> pd.DataFrame:
    """Reassign linked firm-months to the 30-industry set using the SIC code
    of the CRSP observation each row was matched to (`crsp_date`)."""
    from src.clean import _map_industries

    sic = crsp_monthly[["permno", "date", "siccd"]].copy()
    sic["date"] = to_month_end(sic["date"])
    out = ibes.copy()
    out["crsp_date"] = to_month_end(out["crsp_date"])
    out = out.merge(sic, left_on=["permno", "crsp_date"], right_on=["permno", "date"],
                    how="left").drop(columns="date")
    out["industry"] = _map_industries(pd.to_numeric(out["siccd"]), sic30,
                                      config.OTHER_INDUSTRY_30)
    return out


def raw_inputs_available(industry_set: int = 49) -> bool:
    """True when the interim and raw files needed to rebuild signals exist."""
    names = [config.DATA_INTERIM / "ibes_crsp_monthly.parquet",
             config.DATA_RAW / f"kf_ind{industry_set}_vw.parquet",
             config.DATA_RAW / f"kf_sic{industry_set}.parquet"]
    if industry_set == 30:
        names.append(config.DATA_INTERIM / "crsp_monthly.parquet")
    return all(p.exists() for p in names)


def rebuild_signals_from_raw(settings: dict) -> pd.DataFrame:
    """Rebuild the Phase 3 panel from interim/raw files for a raw-only variant."""
    n = settings["industry_set"]
    ibes = pd.read_parquet(config.DATA_INTERIM / "ibes_crsp_monthly.parquet")
    sic = pd.read_parquet(config.DATA_RAW / f"kf_sic{n}.parquet")
    other = config.OTHER_INDUSTRY_49 if n == 49 else config.OTHER_INDUSTRY_30
    if n == 30:
        ibes = remap_to_30_industries(
            ibes, pd.read_parquet(config.DATA_INTERIM / "crsp_monthly.parquet"), sic)
    return signals.build_signals(
        ibes, pd.read_parquet(config.DATA_RAW / f"kf_ind{n}_vw.parquet"), sic,
        min_analysts=settings["min_analysts"], other_industry=other)


def variant_panel(base_panel: pd.DataFrame, settings: dict) -> pd.DataFrame:
    """Phase 3 panel for a variant (before Phase 4 IC and blending)."""
    needs_raw = (settings["min_analysts"] != config.GRID_BASE["min_analysts"]
                 or settings["industry_set"] != config.GRID_BASE["industry_set"])
    panel = (rebuild_signals_from_raw(settings) if needs_raw
             else base_panel[PHASE3_COLUMNS].copy())
    panel["month"] = to_month_end(panel["month"])
    panel["industry"] = pd.to_numeric(panel["industry"]).astype(int)
    if settings["mom_lookback"] != config.MOM_LOOKBACK:
        panel = with_momentum_lookback(panel, settings["mom_lookback"])
    if settings["rev_measure"] == "consensus_change":
        panel["rev"], panel["rev_z"] = panel["rev_alt"], panel["rev_alt_z"]
    return panel


def run_variant(base_panel: pd.DataFrame, settings: dict) -> pd.DataFrame:
    """Blended mean-variance strategy returns for one variant (Phase 4-6)."""
    panel = variant_panel(base_panel, settings)
    blended = ic.run_phase4(panel)["panel"]
    holdings, _ = portfolio.build_holdings(
        blended, {"blend": "blend_z"}, halflife=settings["cov_halflife"],
        target=settings["target_active_risk"],
        beta_neutral=settings["neutrality"] == "dollar_beta", methods=("mv",))
    return backtest.strategy_returns(holdings, risk.returns_from_signal_panel(blended))


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------
def score(results: pd.DataFrame, cost_bps: int, factors: pd.DataFrame | None) -> dict:
    """Net performance on the fixed window and post-2010, plus 6-factor alpha."""
    start, end = (pd.Timestamp(d) for d in config.ROBUSTNESS_WINDOW)
    col = f"net_return_{cost_bps}bps"
    rows = results.copy()
    rows["month"] = to_month_end(rows["month"])
    window = rows.loc[rows["month"].between(start, end)].dropna(subset=["gross_return"])
    post = rows.loc[rows["month"] >= pd.Timestamp(config.POST_SPLIT)].dropna(
        subset=["gross_return"])

    def sharpe(x):
        return x.mean() / x.std(ddof=1) * np.sqrt(config.ANNUALIZE) if len(x) > 2 else np.nan

    out = {"months": len(window),
           "first_formation_month": window["month"].min(),
           "last_formation_month": window["month"].max(),
           "ann_return_net": window[col].mean() * config.ANNUALIZE,
           "ann_vol": window["gross_return"].std(ddof=1) * np.sqrt(config.ANNUALIZE),
           "sharpe_gross": sharpe(window["gross_return"]),
           "sharpe_net": sharpe(window[col]),
           "sharpe_net_post_2010": sharpe(post[col]),
           "avg_monthly_turnover": window["turnover"].mean(),
           "alpha_ann_ff5_umd": np.nan, "alpha_t_ff5_umd": np.nan}
    if factors is not None and len(window):
        merged = attribution.align(window, factors)
        reg = attribution.nw_regression(merged[col], merged[attribution.SPECS["ff5_umd"]])
        out["alpha_ann_ff5_umd"], out["alpha_t_ff5_umd"] = reg["alpha_ann"], reg["alpha_t"]
    return out


def grid_table(runs: dict[str, pd.DataFrame], variants: list[dict],
               factors: pd.DataFrame | None, skipped: dict[str, str]) -> pd.DataFrame:
    """One row per grid setting (cost rows come from the base run)."""
    rows = []
    for v in variants:
        settings = {k: v[k] for k in config.GRID_BASE}
        base_row = {"id": v["id"], "dimension": v["dimension"], "value": v["value"], **settings}
        if v["id"] in skipped:
            rows.append({**base_row, "status": skipped[v["id"]]})
            continue
        rows.append({**base_row, "status": "ok",
                     **score(runs[v["id"]], v["cost_bps"], factors)})
        if v["id"] == "base":
            for c in config.GRID["cost_bps"]:
                if c == v["cost_bps"]:
                    continue
                rows.append({**base_row, "id": f"cost_bps={c}", "dimension": "cost_bps",
                             "value": c, "cost_bps": c, "status": "ok",
                             **score(runs["base"], c, factors)})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Subperiod stability (CLAUDE.md 10.3)
# --------------------------------------------------------------------------
def annual_returns(results: pd.DataFrame, col: str) -> pd.DataFrame:
    """Compounded calendar-year net returns per strategy (mean-variance).

    Partial years (first and last) are flagged by `months` < 12.
    """
    mv = results.loc[results["method"].eq("mv")].dropna(subset=[col]).copy()
    mv["year"] = to_month_end(mv["return_month"]).dt.year
    out = (mv.groupby(["strategy", "year"])
           .agg(net_return=(col, lambda r: float(np.prod(1 + r) - 1)),
                months=(col, "size"))
           .reset_index())
    return out


def stress_months(results: pd.DataFrame, col: str, years=(2009, 2020),
                  factors: pd.DataFrame | None = None) -> pd.DataFrame:
    """Monthly net returns of each strategy in the stress years, with UMD and
    Mkt-RF alongside when factor data are available."""
    mv = results.loc[results["method"].eq("mv")].copy()
    mv["return_month"] = to_month_end(mv["return_month"])
    mv = mv.loc[mv["return_month"].dt.year.isin(years)]
    wide = mv.pivot(index="return_month", columns="strategy", values=col)
    wide.columns = [f"{c}_net" for c in wide.columns]
    if factors is not None:
        wide = wide.join(factors.set_index("date")[["Mkt-RF", "UMD"]], how="left")
    return wide.reset_index()


def rolling_alpha(results: pd.DataFrame, factors: pd.DataFrame, strategy: str = "blend",
                  months: int = config.ROLLING_ALPHA_MONTHS) -> pd.DataFrame:
    """Rolling `months`-month 6-factor alpha (annualized) with Newey-West t,
    dated by the last return month in each window."""
    col = f"net_return_{config.BASE_COST_BPS}bps"
    g = (results.loc[results["strategy"].eq(strategy) & results["method"].eq("mv")]
         .dropna(subset=[col]).sort_values("return_month"))
    merged = attribution.align(g, factors).reset_index(drop=True)
    rows = []
    for end in range(months, len(merged) + 1):
        w = merged.iloc[end - months:end]
        reg = attribution.nw_regression(w[col], w[attribution.SPECS["ff5_umd"]])
        rows.append({"return_month": w["return_month"].iloc[-1],
                     "alpha_ann": reg["alpha_ann"], "alpha_t": reg["alpha_t"]})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Figures
# --------------------------------------------------------------------------
def plot_heatmap(grid: pd.DataFrame, path: Path) -> Path:
    """Net Sharpe over momentum lookback x covariance half-life (base costs)."""
    from src import plots
    import matplotlib.pyplot as plt

    cells = grid.loc[grid["status"].eq("ok") & grid["cost_bps"].eq(config.BASE_COST_BPS)
                     & grid["min_analysts"].eq(config.GRID_BASE["min_analysts"])
                     & grid["industry_set"].eq(config.GRID_BASE["industry_set"])
                     & grid["neutrality"].eq(config.GRID_BASE["neutrality"])
                     & grid["rev_measure"].eq(config.GRID_BASE["rev_measure"])
                     & grid["target_active_risk"].eq(config.GRID_BASE["target_active_risk"])]
    table = cells.pivot_table(index="mom_lookback", columns="cov_halflife",
                              values="sharpe_net", aggfunc="first")
    fig, ax = plots.new_figure(7.0, 4.8)
    ax.grid(False)
    lim = max(0.05, float(np.nanmax(np.abs(table.to_numpy()))))
    image = ax.imshow(table.to_numpy(), cmap="RdBu", vmin=-lim, vmax=lim, aspect="auto")
    ax.set_xticks(range(len(table.columns)), [str(c) for c in table.columns])
    ax.set_yticks(range(len(table.index)), [str(i) for i in table.index])
    for i in range(table.shape[0]):
        for j in range(table.shape[1]):
            value = table.iat[i, j]
            ax.text(j, i, "n/a" if pd.isna(value) else f"{value:.2f}", ha="center",
                    va="center", color=plots.INK, fontsize=11)
    fig.colorbar(image, ax=ax, label=f"Net Sharpe ({config.BASE_COST_BPS} bp)")
    start, end = (pd.Timestamp(d) for d in config.ROBUSTNESS_WINDOW)
    return plots.finish(
        fig, ax,
        title=f"Blended strategy net Sharpe, formation {start:%b %Y}–{end:%b %Y}",
        xlabel="Covariance half-life (months)", ylabel="Momentum lookback (months)",
        path=path, legend=False)


def plot_annual(annual: pd.DataFrame, path: Path) -> Path:
    """Grouped bars of calendar-year net returns for MOM and the blend."""
    from src import plots

    wide = annual.pivot(index="year", columns="strategy", values="net_return")
    wide = wide[[c for c in ("mom", "blend") if c in wide.columns]].dropna(how="all")
    wide = wide.loc[wide.index >= pd.Timestamp(config.ROBUSTNESS_WINDOW[0]).year]
    fig, ax = plots.new_figure(10, 4.8)
    width = 0.4
    x = np.arange(len(wide))
    for i, (col, label) in enumerate([("mom", "MOM"), ("blend", "Blend")]):
        if col in wide:
            ax.bar(x + (i - 0.5) * width, wide[col] * 100, width=width * 0.92,
                   color=plots.SERIES[0 if col == "mom" else 3], label=label)
    ax.axhline(0, color=plots.BASELINE, linewidth=1.0)
    ax.set_xticks(x[::2], [str(y) for y in wide.index[::2]], rotation=0)
    return plots.finish(
        fig, ax,
        title=f"Calendar-year net return ({config.BASE_COST_BPS} bp), mean-variance books, "
              f"{wide.index.min()}–{wide.index.max()} (first/last years partial)",
        xlabel="Calendar year of return", ylabel="Net return (%)", path=path)


def plot_rolling_alpha(roll: pd.DataFrame, path: Path) -> Path:
    """Rolling 6-factor alpha of the blend with a +/-2 t-stat band marker."""
    from src import plots

    fig, ax = plots.new_figure()
    ax.plot(roll["return_month"], roll["alpha_ann"] * 100, color=plots.SERIES[3],
            linewidth=1.6, label=f"{config.ROLLING_ALPHA_MONTHS}-month alpha")
    sig = roll.loc[roll["alpha_t"].abs() >= 2]
    ax.scatter(sig["return_month"], sig["alpha_ann"] * 100, s=14, color=plots.SERIES[1],
               zorder=3, label="|t| >= 2")
    ax.axhline(0, color=plots.BASELINE, linewidth=1.0)
    return plots.finish(
        fig, ax,
        title=f"Blend rolling {config.ROLLING_ALPHA_MONTHS}-month FF5+UMD alpha, net "
              f"{config.BASE_COST_BPS} bp, {roll['return_month'].min():%b %Y}–"
              f"{roll['return_month'].max():%b %Y}",
        xlabel="Last return month of window", ylabel="Annualized alpha (%)", path=path)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def load_factors_if_available() -> pd.DataFrame | None:
    """Merged Ken French factors, or None when the raw files are absent."""
    paths = [config.DATA_RAW / f"{n}.parquet" for n in ("kf_ff5", "kf_umd", "kf_strev")]
    if not all(p.exists() for p in paths):
        return None
    return attribution.load_factors(*(pd.read_parquet(p) for p in paths))


def main(alphas_only: bool = False) -> None:
    """Run the grid (or reuse saved runs), then write tables and figures."""
    factors = load_factors_if_available()
    variants = grid_variants()
    returns_path = config.TABLES / "robustness_returns_by_month.csv"
    skipped: dict[str, str] = {}
    runs: dict[str, pd.DataFrame] = {}
    if alphas_only:
        saved = pd.read_csv(returns_path, parse_dates=["month", "return_month"])
        runs = {k: g.drop(columns="variant") for k, g in saved.groupby("variant")}
        skipped = {v["id"]: "skipped: not in saved runs" for v in variants
                   if v["id"] not in runs}
    else:
        base_panel = pd.read_parquet(config.DATA_PROCESSED / "signals_phase4.parquet")
        for v in variants:
            needs_raw = v["dimension"] in NEEDS_RAW
            if needs_raw and not raw_inputs_available(v["industry_set"]):
                skipped[v["id"]] = "skipped: needs data/raw and data/interim"
                print(f"skip {v['id']}: raw inputs not available")
                continue
            print(f"run {v['id']} ...", flush=True)
            runs[v["id"]] = run_variant(base_panel, v)
        saved = pd.concat([r.assign(variant=k) for k, r in runs.items()], ignore_index=True)
        config.TABLES.mkdir(parents=True, exist_ok=True)
        saved.to_csv(returns_path, index=False)

    grid = grid_table(runs, variants, factors, skipped)
    grid.to_csv(config.TABLES / "robustness_grid.csv", index=False)
    plot_heatmap(grid, config.FIGURES / "robustness_heatmap_sharpe.png")

    col = f"net_return_{config.BASE_COST_BPS}bps"
    base_results = pd.read_csv(config.TABLES / "strategy_returns_by_month.csv",
                               parse_dates=["month", "return_month"])
    annual = annual_returns(base_results, col)
    annual.to_csv(config.TABLES / "annual_returns.csv", index=False)
    plot_annual(annual, config.FIGURES / "annual_returns.png")
    stress_months(base_results, col, factors=factors).to_csv(
        config.TABLES / "stress_2009_2020.csv", index=False)
    if factors is not None:
        roll = rolling_alpha(base_results, factors)
        roll.to_csv(config.TABLES / "rolling_alpha_blend.csv", index=False)
        plot_rolling_alpha(roll, config.FIGURES / "rolling_alpha_blend.png")
    else:
        print("factor files not found: alphas and rolling alpha skipped "
              "(rerun with --alphas-only where data/raw exists)")
    show = ["id", "status", "months", "sharpe_gross", "sharpe_net", "sharpe_net_post_2010",
            "avg_monthly_turnover", "alpha_ann_ff5_umd", "alpha_t_ff5_umd"]
    print(grid[show].to_string(index=False, float_format=lambda v: f"{v:.3f}"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--alphas-only", action="store_true",
                        help="reuse saved grid runs; add factor alphas and rolling alpha")
    main(alphas_only=parser.parse_args().alphas_only)
