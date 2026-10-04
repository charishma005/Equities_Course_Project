"""Phase 6: backtest, turnover, and transaction costs (CLAUDE.md 8).

Timing: holdings h(t) are formed at month-end t and earn the industry returns
of month t+1: gross(t+1) = sum_n h_n(t) r_n(t+1). Trading to reach h(t)
happens at t, so its cost is charged against the t+1 return:
net(t+1) = gross(t+1) - cost * turnover(t).

Turnover(t) = sum_n |h_n(t) - drift_n|, where drift is h(t-1) after month-t
returns: drift_n = h_n(t-1) (1 + r_n(t)) / (1 + g(t)), g(t) the book's month-t
return. If the strategy held nothing at t-1 (first month or a gap), the whole
book is traded: turnover(t) = sum_n |h_n(t)|.

The books are dollar neutral, so their returns are already excess returns
(RF earned on the margin cash cancels the financing of the longs) and the
Sharpe ratio is mean / std. Annual return = 12 * mean monthly return.
Windows are defined by formation month t, as in Phases 4 and 5.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src import risk  # noqa: E402
from src.utils import to_month_end  # noqa: E402

LABELS = {"mom": "MOM", "rev": "REV", "rev_orth": "REV orthogonal", "blend": "Blend"}


def strategy_returns(holdings: pd.DataFrame, returns: pd.DataFrame,
                     costs_bps=config.COSTS_BPS) -> pd.DataFrame:
    """Monthly gross and net returns and turnover for every strategy/method.

    Inputs: holdings (month, strategy, method, industry, weight) dated by
    formation month t; returns, a wide panel indexed by return month.
    Output: one row per (strategy, method, formation month t) with
    return_month = t+1, gross_return, turnover, rebuild flag, and
    net_return_<c>bps for each cost c. Returns are NaN when any held
    industry's t+1 return is not yet observed.
    """
    holdings = holdings.copy()
    holdings["month"] = to_month_end(holdings["month"])
    industries = list(returns.columns)
    rows = []
    for (strategy, method), g in holdings.groupby(["strategy", "method"], sort=False):
        wide = (g.pivot(index="month", columns="industry", values="weight")
                .reindex(columns=industries).fillna(0.0).sort_index())
        prev_month, prev_h = None, None
        for month, h_row in wide.iterrows():
            h = h_row.to_numpy(dtype=float)
            if prev_month is not None and prev_month + pd.offsets.MonthEnd(1) == month:
                r_t = returns.loc[month].to_numpy(dtype=float) if month in returns.index \
                    else np.full(len(h), np.nan)
                held = prev_h != 0
                book_t = float(prev_h[held] @ r_t[held])
                drift = prev_h * (1 + np.nan_to_num(r_t)) / (1 + book_t)
                turnover = float(np.abs(h - drift).sum())
                rebuild = False
            else:
                turnover, rebuild = float(np.abs(h).sum()), True
            next_month = to_month_end(pd.Series([month + pd.offsets.MonthEnd(1)])).iloc[0]
            if next_month in returns.index:
                r_next = returns.loc[next_month].to_numpy(dtype=float)
                held = h != 0
                gross = float(h[held] @ r_next[held]) if np.isfinite(r_next[held]).all() \
                    else np.nan
            else:
                gross = np.nan
            row = {"strategy": strategy, "method": method, "month": month,
                   "return_month": next_month, "gross_return": gross,
                   "turnover": turnover, "rebuild": rebuild,
                   "gross_exposure": float(np.abs(h).sum())}
            for c in costs_bps:
                row[f"net_return_{c}bps"] = gross - c / 1e4 * turnover
            rows.append(row)
            prev_month, prev_h = month, h
    return pd.DataFrame(rows)


def max_drawdown(monthly_returns: pd.Series) -> float:
    """Largest peak-to-trough decline of cumulative wealth prod(1 + r), as a
    negative fraction (e.g. -0.25 = -25%). NaN for an empty series."""
    r = monthly_returns.dropna()
    if r.empty:
        return np.nan
    wealth = (1 + r).cumprod()
    peak = np.maximum.accumulate(np.concatenate([[1.0], wealth.to_numpy()]))[1:]
    return float((wealth.to_numpy() / peak - 1).min())


def drawdown_series(monthly_returns: pd.Series) -> pd.Series:
    """Drawdown from the running peak of cumulative wealth, by month."""
    wealth = (1 + monthly_returns.fillna(0)).cumprod()
    peak = np.maximum(wealth.cummax(), 1.0)
    return wealth / peak - 1


def _perf(g: pd.DataFrame, costs_bps) -> dict:
    """Performance statistics over the rows of one window (realized only)."""
    real = g.dropna(subset=["gross_return"])
    out = {"months": len(g), "months_with_returns": len(real),
           "first_return_month": real["return_month"].min(),
           "last_return_month": real["return_month"].max()}
    k = config.ANNUALIZE
    gross = real["gross_return"]
    out["ann_return_gross"] = gross.mean() * k
    out["ann_vol_gross"] = gross.std(ddof=1) * np.sqrt(k)
    out["sharpe_gross"] = out["ann_return_gross"] / out["ann_vol_gross"] \
        if out["ann_vol_gross"] > 0 else np.nan
    out["max_drawdown_gross"] = max_drawdown(gross)
    out["avg_monthly_turnover"] = g["turnover"].mean()
    out["avg_gross_exposure"] = g["gross_exposure"].mean()
    for c in costs_bps:
        net = real[f"net_return_{c}bps"]
        vol = net.std(ddof=1) * np.sqrt(k)
        out[f"ann_return_net_{c}bps"] = net.mean() * k
        out[f"sharpe_net_{c}bps"] = net.mean() * k / vol if vol > 0 else np.nan
    out[f"max_drawdown_net_{config.BASE_COST_BPS}bps"] = max_drawdown(
        real[f"net_return_{config.BASE_COST_BPS}bps"])
    return out


def window_bounds(results: pd.DataFrame, panel_last_month: pd.Timestamp,
                  primary_method: str = "mv") -> dict[str, tuple]:
    """Formation-month windows: common (months where every strategy has a
    realized primary-method return), post_2010, and the last RECENT_MONTHS
    signal months of the panel (fixed, not shifted to complete coverage)."""
    primary = results.loc[results["method"].eq(primary_method)].dropna(
        subset=["gross_return"])
    per_strategy = primary.groupby("strategy")["month"].agg(["min", "max"])
    recent_start = panel_last_month - pd.offsets.MonthEnd(config.RECENT_MONTHS - 1)
    return {
        "common": (per_strategy["min"].max(), per_strategy["max"].min()),
        "post_2010": (pd.Timestamp(config.POST_SPLIT), panel_last_month),
        f"recent_{config.RECENT_MONTHS}m": (recent_start, panel_last_month),
    }


def performance_table(results: pd.DataFrame, panel_last_month: pd.Timestamp,
                      costs_bps=config.COSTS_BPS) -> pd.DataFrame:
    """Performance per strategy, method, and window (full = own history)."""
    bounds = window_bounds(results, panel_last_month)
    rows = []
    for (strategy, method), g in results.groupby(["strategy", "method"], sort=False):
        windows = {"full": g}
        for name, (start, end) in bounds.items():
            windows[name] = g.loc[g["month"].between(start, end)]
        for name, w in windows.items():
            row = {"strategy": strategy, "method": method, "window": name,
                   "window_start": w["month"].min() if name == "full" else bounds[name][0],
                   "window_end": w["month"].max() if name == "full" else bounds[name][1]}
            row.update(_perf(w, costs_bps))
            rows.append(row)
    return pd.DataFrame(rows)


def plot_cumulative(results: pd.DataFrame, start, end, path: Path) -> Path:
    """Cumulative net (base-cost) growth of $1 for each strategy, log scale."""
    from src import plots

    col = f"net_return_{config.BASE_COST_BPS}bps"
    mv = results.loc[results["method"].eq("mv") & results["month"].between(start, end)]
    fig, ax = plots.new_figure()
    for i, (strategy, g) in enumerate(mv.groupby("strategy", sort=False)):
        g = g.dropna(subset=[col]).sort_values("return_month")
        ax.plot(g["return_month"], (1 + g[col]).cumprod(), color=plots.SERIES[i],
                linewidth=1.6, label=LABELS.get(strategy, strategy))
    ax.axhline(1, color=plots.BASELINE, linewidth=1.0)
    ax.set_yscale("log")
    first = mv.dropna(subset=[col])["return_month"]
    return plots.finish(
        fig, ax,
        title=f"Cumulative net return, {config.BASE_COST_BPS} bp one-way cost, "
              f"{first.min():%b %Y}–{first.max():%b %Y}",
        xlabel="Return month (month-end)",
        ylabel="Growth of $1 (log scale)", path=path)


def plot_blend_drawdown(results: pd.DataFrame, path: Path) -> Path:
    """Drawdown of the blended mean-variance strategy, net of base cost."""
    from src import plots

    col = f"net_return_{config.BASE_COST_BPS}bps"
    g = (results.loc[results["strategy"].eq("blend") & results["method"].eq("mv")]
         .dropna(subset=[col]).sort_values("return_month"))
    dd = drawdown_series(g.set_index("return_month")[col])
    fig, ax = plots.new_figure()
    ax.fill_between(dd.index, dd.to_numpy() * 100, 0, color=plots.SERIES[3], alpha=0.35,
                    linewidth=0)
    ax.plot(dd.index, dd.to_numpy() * 100, color=plots.SERIES[3], linewidth=1.2)
    return plots.finish(
        fig, ax,
        title=f"Blended strategy drawdown, net of {config.BASE_COST_BPS} bp, "
              f"{dd.index.min():%b %Y}–{dd.index.max():%b %Y}",
        xlabel="Return month (month-end)", ylabel="Drawdown from peak (%)",
        path=path, legend=False)


def main() -> None:
    """Run the Phase 6 backtest from Phase 5 holdings and save outputs."""
    panel = pd.read_parquet(config.DATA_PROCESSED / "signals_phase4.parquet")
    holdings = pd.read_parquet(config.DATA_PROCESSED / "holdings.parquet")
    returns = risk.returns_from_signal_panel(panel)
    results = strategy_returns(holdings, returns)
    last_month = to_month_end(panel["month"]).max()
    perf = performance_table(results, last_month)
    config.TABLES.mkdir(parents=True, exist_ok=True)
    results.to_csv(config.TABLES / "strategy_returns_by_month.csv", index=False)
    perf.to_csv(config.TABLES / "performance_by_window.csv", index=False)
    common = window_bounds(results, last_month)["common"]
    plot_cumulative(results, *common, config.FIGURES / "cumulative_net_returns.png")
    plot_blend_drawdown(results, config.FIGURES / "blend_drawdown.png")
    cols = ["strategy", "method", "window", "months_with_returns", "ann_return_gross",
            "ann_vol_gross", "sharpe_gross", "avg_monthly_turnover",
            "sharpe_net_10bps", "sharpe_net_20bps", "sharpe_net_30bps",
            f"max_drawdown_net_{config.BASE_COST_BPS}bps"]
    print(perf[cols].to_string(index=False))
    too_good = perf.loc[perf[f"sharpe_net_{config.BASE_COST_BPS}bps"] > 1.5]
    if not too_good.empty:
        print("\nWARNING: net Sharpe > 1.5 -- check for look-ahead (CLAUDE.md 13):")
        print(too_good[["strategy", "method", "window"]].to_string(index=False))


if __name__ == "__main__":
    main()
