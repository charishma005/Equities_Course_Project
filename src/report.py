"""Phase 9: collect the key results into results/summary.md (CLAUDE.md 11).

Reads only the committed result tables in results/tables, so it needs no
WRDS data and can be rerun after any phase is rerun. Every number in the
summary, including the draft executive summary, is taken from those tables.

Usage:
    python -m src.report
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

LABELS = {"mom": "MOM", "rev": "REV", "rev_alt": "REV (consensus change)",
          "rev_orth": "REV orthogonal", "blend": "Blend"}
WINDOW_LABELS = {"full": "Full", "rev_sample": "REV sample", "common": "Common",
                 "post_2010": "Post-2010", "recent_18m": "Recent 18m"}

FIGURE_CAPTIONS = {
    "mom_rev_correlation.png":
        "Monthly cross-sectional correlation between industry MOM and REV (Phase 3).",
    "rolling_ic_mom_rev.png":
        "12-month rolling mean Spearman IC of MOM and REV (Phase 4).",
    "blend_weights.png":
        "Expanding-window IC-based blend weights on MOM and REV (Phase 4).",
    "lambda_over_time.png":
        "Implied risk aversion λ that sets ex-ante active risk to 5% each month (Phase 5).",
    "cumulative_net_returns.png":
        "Cumulative net returns at 20 bp of the four strategies, common window, log scale (Phase 6).",
    "blend_drawdown.png":
        "Drawdown of the blended strategy net of 20 bp (Phase 6).",
    "robustness_heatmap_sharpe.png":
        "Blend net Sharpe over momentum lookback × covariance half-life (Phase 8).",
    "annual_returns.png":
        "Calendar-year net returns of MOM and the blend (Phase 8).",
    "rolling_alpha_blend.png":
        "Rolling 36-month FF5+UMD alpha of the blend; dots mark |t| ≥ 2 (Phase 8).",
}


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------
def _no_negative_zero(x: float, digits: int) -> float:
    """Values that round to zero print as 0, not -0."""
    return 0.0 if round(x, digits) == 0 else x


def pct(x, digits=1) -> str:
    """Decimal -> signed percent string (0.012 -> '+1.2%'); blank for missing."""
    if pd.isna(x):
        return ""
    x = _no_negative_zero(x * 100, digits)
    return f"{x:.{digits}f}%" if x == 0 else f"{x:+.{digits}f}%"


def num(x, digits=2) -> str:
    """Number with fixed decimals; blank for missing; no '-0.00'."""
    return "" if pd.isna(x) else f"{_no_negative_zero(x, digits):.{digits}f}"


def md_table(df: pd.DataFrame) -> str:
    """Render a DataFrame of strings/numbers as a GitHub markdown table."""
    cols = list(df.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |",
             "|" + "|".join("---" for _ in cols) + "|"]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |")
    return "\n".join(lines)


def _read(name: str, tables: Path) -> pd.DataFrame:
    return pd.read_csv(tables / f"{name}.csv")


# --------------------------------------------------------------------------
# Section builders (each returns a markdown table)
# --------------------------------------------------------------------------
def ic_table(tables: Path) -> str:
    """Phase 4: Spearman IC by signal and window, with Newey-West t."""
    ic = _read("ic_summary_by_horizon", tables)
    ic = ic.loc[ic["window"].isin(["rev_sample", "post_2010", "recent_18m"])]
    out = pd.DataFrame({
        "Window": ic["window"].map(WINDOW_LABELS),
        "Signal": ic["signal"].map(LABELS),
        "IC months": ic["ic_months"],
        "Mean IC": ic["spearman_mean"].map(lambda v: num(v, 3)),
        "IC std": ic["spearman_std"].map(lambda v: num(v, 3)),
        "t (NW)": ic["spearman_tstat_nw"].map(num),
        "IC IR": ic["spearman_ir"].map(num),
        "% IC > 0": ic["spearman_positive_pct"].map(lambda v: num(v, 0)),
    })
    return md_table(out)


def risk_table(tables: Path) -> str:
    """Phase 5: λ and ex-ante vs. realized active risk (mean-variance books)."""
    r = _read("portfolio_risk_summary", tables)
    r = r.loc[r["method"].eq("mv")]
    out = pd.DataFrame({
        "Strategy": r["strategy"].map(LABELS),
        "Months": r["months"],
        "Ex-ante risk": r["exante_active_risk_ann_mean"].map(lambda v: f"{v:.1%}"),
        "Realized active vol": r["realized_active_vol_ann"].map(lambda v: f"{v:.1%}"),
        "Median λ": r["lambda_median"].map(num),
        "λ 10th–90th pct": [f"{a:.2f}–{b:.2f}" for a, b in zip(r["lambda_p10"], r["lambda_p90"])],
        "Mean gross": r["gross_exposure_mean"].map(lambda v: f"{v:.2f}x"),
    })
    return md_table(out)


def performance_table(tables: Path) -> str:
    """Phase 6: performance by window, mean-variance books."""
    p = _read("performance_by_window", tables)
    p = p.loc[p["method"].eq("mv") & p["window"].isin(["common", "post_2010", "recent_18m"])]
    out = pd.DataFrame({
        "Window": p["window"].map(WINDOW_LABELS),
        "Strategy": p["strategy"].map(LABELS),
        "Months": p["months_with_returns"],
        "Gross ann. return": p["ann_return_gross"].map(pct),
        "Vol": p["ann_vol_gross"].map(lambda v: f"{v:.1%}"),
        "Gross Sharpe": p["sharpe_gross"].map(num),
        "Monthly turnover": p["avg_monthly_turnover"].map(lambda v: f"{v:.0%}"),
        "Net Sharpe 10/20/30 bp": [f"{num(a)} / {num(b)} / {num(c)}" for a, b, c in
                                   zip(p["sharpe_net_10bps"], p["sharpe_net_20bps"],
                                       p["sharpe_net_30bps"])],
        "Max DD (20 bp)": p["max_drawdown_net_20bps"].map(lambda v: f"{v:.0%}"),
    })
    return md_table(out)


def factor_table(tables: Path, spec: str = "ff5_umd") -> str:
    """Phase 7: alpha and loadings, net of 20 bp, mean-variance books."""
    f = _read("factor_regressions", tables)
    f = f.loc[f["method"].eq("mv") & f["spec"].eq(spec)
              & f["window"].isin(["common", "post_2010", "recent_18m"])]
    factors = ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "UMD"] + (
        ["ST_Rev"] if spec == "ff5_umd_strev" else [])
    out = pd.DataFrame({
        "Window": f["window"].map(WINDOW_LABELS),
        "Strategy": f["strategy"].map(LABELS),
        "Months": f["n"],
        "Alpha (ann.)": f["alpha_ann"].map(pct),
        "t": f["alpha_t"].map(num),
    })
    for c in factors:
        out[f"β {c} (t)"] = [f"{num(b)} ({num(t, 1)})" for b, t in
                             zip(f[f"beta_{c}"], f[f"t_{c}"])]
    out["R²"] = f["r2"].map(num)
    return md_table(out)


def umd_table(tables: Path) -> str:
    """Phase 7 key comparison: alpha with vs. without UMD, criterion flag."""
    u = _read("alpha_with_without_umd", tables)
    out = pd.DataFrame({
        "Window": u["window"].map(WINDOW_LABELS),
        "Strategy": u["strategy"].map(LABELS),
        "Months": u["months"],
        "Alpha FF5+UMD": u["alpha_ann_ff5_umd"].map(pct),
        "t": u["alpha_t_ff5_umd"].map(num),
        "UMD β (t)": [f"{num(b)} ({num(t, 1)})" for b, t in
                      zip(u["beta_UMD_ff5_umd"], u["t_UMD_ff5_umd"])],
        "Alpha FF5 only": u["alpha_ann_ff5"].map(pct),
        "t ": u["alpha_t_ff5"].map(num),
        "Passes criterion": u["passes_criterion"],
    })
    return md_table(out)


def horizon_table(tables: Path) -> str:
    """Phase 8 horizon splits: coverage, net Sharpe, and 6-factor alpha t per
    strategy and window (full / post-2010 / recent 18 months)."""
    cov = _read("signal_coverage_by_horizon", tables)
    perf = _read("performance_by_window", tables)
    reg = _read("factor_regressions", tables)
    perf = perf.loc[perf["method"].eq("mv")]
    reg = reg.loc[reg["method"].eq("mv") & reg["spec"].eq("ff5_umd")]
    rows = []
    for window in ["full", "post_2010", "recent_18m"]:
        for strategy in ["mom", "rev", "rev_orth", "blend"]:
            p = perf.loc[perf["window"].eq(window) & perf["strategy"].eq(strategy)]
            g = reg.loc[reg["window"].eq(window) & reg["strategy"].eq(strategy)]
            sig = "rev" if strategy in ("rev", "rev_orth") else "mom"
            c = cov.loc[cov["window"].eq(window) & cov["signal"].eq(sig)]
            rows.append({
                "Window": WINDOW_LABELS[window], "Strategy": LABELS[strategy],
                "Signal months / evaluable":
                    "" if c.empty else f"{int(c['months_with_signal'].iloc[0])} / "
                                       f"{int(c['months_evaluable'].iloc[0])}",
                "Return months": "" if p.empty else int(p["months_with_returns"].iloc[0]),
                "Net Sharpe (20 bp)": "" if p.empty else num(p["sharpe_net_20bps"].iloc[0]),
                "Alpha t (FF5+UMD)": "" if g.empty else num(g["alpha_t"].iloc[0]),
            })
    note = ("Coverage columns refer to the strategy's main input signal (MOM for "
            "MOM and Blend; REV for REV and REV orthogonal) over the window's signal "
            "months; the full window for coverage starts in 1926, while strategy "
            "returns start when holdings do.")
    return md_table(pd.DataFrame(rows)) + "\n\n" + note


def robustness_table(tables: Path) -> str:
    """Phase 8 one-at-a-time grid for the blend."""
    g = _read("robustness_grid", tables)
    out = pd.DataFrame({
        "Setting": g["id"].str.replace("heatmap:", "", regex=False),
        "Status": g["status"],
        "Net Sharpe": g["sharpe_net"].map(num),
        "Net Sharpe post-2010": g["sharpe_net_post_2010"].map(num),
        "Monthly turnover": g["avg_monthly_turnover"].map(
            lambda v: "" if pd.isna(v) else f"{v:.0%}"),
        "Alpha FF5+UMD": g["alpha_ann_ff5_umd"].map(pct),
        "t": g["alpha_t_ff5_umd"].map(num),
    })
    return md_table(out)


def figure_list(figures: Path) -> str:
    """Bulleted list of every PNG with its caption; flags uncaptioned files."""
    lines = []
    for path in sorted(figures.glob("*.png")):
        caption = FIGURE_CAPTIONS.get(path.name, "**Caption missing — add to src/report.py.**")
        lines.append(f"- `results/figures/{path.name}`: {caption}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Draft executive summary
# --------------------------------------------------------------------------
def executive_summary(tables: Path) -> str:
    """Draft one-paragraph executive summary built from the result tables."""
    ic = _read("ic_summary_by_horizon", tables).set_index(["window", "signal"])
    u = _read("alpha_with_without_umd", tables).set_index(["window", "strategy"])
    perf = _read("performance_by_window", tables)
    perf = perf.loc[perf["method"].eq("mv")].set_index(["window", "strategy"])
    grid = _read("robustness_grid", tables)
    ok = grid.loc[grid["status"].eq("ok")]
    best_t = ok["alpha_t_ff5_umd"].max()
    common = u.xs("common")
    post = u.xs("post_2010")
    tested = u.loc[~u["passes_criterion"].eq("low power")]
    best_tested_t = tested["alpha_t_ff5_umd"].max()
    low = u.loc[u["passes_criterion"].eq("low power")]
    low_hi = low.loc[low["alpha_t_ff5_umd"] >= 2]
    low_note = "" if low_hi.empty else (
        " The only t above 2 is in the recent 18-month window ("
        + ", ".join(f"{LABELS[s]} t {num(t)} on {int(m)} months" for (w, s), t, m in
                    zip(low_hi.index, low_hi["alpha_t_ff5_umd"], low_hi["months"]))
        + "), too few observations for the regression to be informative.")
    return (
        "We tested whether industry-level analyst EPS revisions (I/B/E/S) predict "
        "next-month returns of the 49 Fama-French industries beyond industry "
        "momentum, combining the two signals with IC-based weights in a "
        "dollar-neutral mean-variance portfolio targeted at 5% active risk. "
        f"Over 1985–2025 the revision signal's mean IC was "
        f"{num(ic.loc[('rev_sample', 'rev'), 'spearman_mean'], 3)} "
        f"(Newey-West t {num(ic.loc[('rev_sample', 'rev'), 'spearman_tstat_nw'])}), and the part "
        f"orthogonal to momentum had an IC of "
        f"{num(ic.loc[('rev_sample', 'rev_orth'), 'spearman_mean'], 3)} "
        f"(t {num(ic.loc[('rev_sample', 'rev_orth'), 'spearman_tstat_nw'])}). "
        f"Revision portfolios turned over about "
        f"{perf.loc[('common', 'rev'), 'avg_monthly_turnover']:.0%} of capital a month, and net "
        f"of 20 bp their FF5+UMD alpha was "
        f"{pct(common.loc['rev', 'alpha_ann_ff5_umd'])} per year "
        f"(t {num(common.loc['rev', 'alpha_t_ff5_umd'])}) over 1995–2025. The blended "
        f"strategy's alpha against FF5 alone, "
        f"{pct(common.loc['blend', 'alpha_ann_ff5'])} (t {num(common.loc['blend', 'alpha_t_ff5'])}), "
        f"falls to {pct(common.loc['blend', 'alpha_ann_ff5_umd'])} "
        f"(t {num(common.loc['blend', 'alpha_t_ff5_umd'])}) once UMD is added, and to "
        f"{pct(post.loc['blend', 'alpha_ann_ff5_umd'])} (t {num(post.loc['blend', 'alpha_t_ff5_umd'])}) "
        "after 2010: its return is momentum exposure. No strategy has a positive "
        "FF5+UMD net alpha with t ≥ 2 in the full, common, or post-2010 windows "
        f"(highest t {num(best_tested_t)}), and neither does any robustness setting "
        f"(highest t {num(best_t)})." + low_note + " Revisions do not add alpha beyond "
        "momentum, and by our pre-registered criterion we conclude: "
        "**do not implement.**"
    )


REPORT_MAP = """\
| Report section | Use |
|---|---|
| 1. Executive Summary | Draft above (team to edit; written last) |
| 2. What Did You Try? — thesis, rejection criterion | CLAUDE.md §0 (fixed before testing) |
| 2. Data | README Phase 1–2 notes; `ibes_link_rate_by_year.csv`, `ibes_industry_coverage.csv`; CRSP ends Dec 2025, so REV is missing for 2026 (CLAUDE.md 4.4); 2026 CUSIP/ACTPSUM sensitivity reported separately |
| 2. Signal construction | CLAUDE.md §5; `signal_summary.csv`, `signal_coverage_by_month.csv`; `mom_rev_correlation.png` |
| 2. Risk model, sizing, λ | §2 table; 50% covariance shrinkage decision (CLAUDE.md 7.1); `lambda_over_time.png` |
| 3. What Did You Learn? — ICs and incremental information | §1 table; `rolling_ic_mom_rev.png`, `blend_weights.png` |
| 3. Performance and costs | §3 table; `cumulative_net_returns.png`, `blend_drawdown.png` |
| 3. Factor exposures | §4 tables (UMD loadings, alpha with/without UMD) |
| 3. Time patterns | §5 horizon table; `annual_returns.png`, `rolling_alpha_blend.png`; `stress_2009_2020.csv` |
| 3. Robustness | §6 grid; `robustness_heatmap_sharpe.png` |
| 3. Evaluation of the AI's role | `ai_log/ai_interactions.md` — team-written critical evaluations; note the logged AI errors (Python 3.9 hints, 2025 sample cutoff that shifted the recent window, low-power pass flag, pandas 2.2 alignment crash) |
| 4. Appendices | Full AI log; all CSVs in `results/tables/`; all figures (§7); code in `src/` |
"""


def build_summary(tables: Path = config.TABLES, figures: Path = config.FIGURES) -> str:
    """Assemble the full results/summary.md text."""
    sections = [
        "# Results summary\n",
        "Generated by `python -m src.report` from `results/tables/`. Mean-variance "
        "books, dollar neutral, 5% ex-ante active risk, covariance shrunk 50% toward "
        "its diagonal. Windows are by formation month: Common = Jan 1995–Dec 2025 "
        "(all four strategies trade), Post-2010 = Jan 2010 on, Recent 18m = Mar "
        "2025–Aug 2026 (low power; REV has 10 evaluable months). Newey-West t-stats "
        "use 6 lags. Alphas are net of 20 bp one-way costs.\n",
        "## Draft executive summary (for the team to edit)\n",
        executive_summary(tables) + "\n",
        "## 1. Information coefficients (Phase 4)\n",
        "Spearman IC of signal z-scores at t against industry returns at t+1. "
        "REV sample = Jan 1985–Dec 2025, the months with primary REV.\n",
        ic_table(tables) + "\n",
        "## 2. Risk and λ (Phase 5)\n",
        risk_table(tables) + "\n",
        "## 3. Performance (Phase 6)\n",
        performance_table(tables) + "\n",
        "## 4. Factor attribution (Phase 7)\n",
        "### FF5 + UMD (primary)\n",
        factor_table(tables, "ff5_umd") + "\n",
        "### Alpha with vs. without UMD, and the rejection criterion\n",
        "`Passes criterion` = yes only for a positive FF5+UMD net alpha with t ≥ 2; "
        "windows under 36 months read \"low power\".\n",
        umd_table(tables) + "\n",
        "### FF5 + UMD + short-term reversal (robustness)\n",
        factor_table(tables, "ff5_umd_strev") + "\n",
        "## 5. Horizon splits (Phase 8)\n",
        horizon_table(tables) + "\n",
        "## 6. Robustness grid, blended strategy (Phase 8)\n",
        "One change from the base case per row; all rows scored on formation "
        "Jan 1995–Dec 2025. The min-analysts and 30-industry rows were rebuilt from "
        "a machine whose cleaned CRSP panel differs from the one behind the "
        "committed signals (see README); rerun them before quoting.\n",
        robustness_table(tables) + "\n",
        "## 7. Figures\n",
        figure_list(figures) + "\n",
        "## 8. Report checklist\n",
        REPORT_MAP,
    ]
    return "\n".join(sections)


def main() -> None:
    """Write results/summary.md."""
    text = build_summary()
    path = config.RESULTS / "summary.md"
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path} ({len(text.splitlines())} lines)")


if __name__ == "__main__":
    main()
