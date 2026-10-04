# Industry Analyst Revisions vs. Industry Momentum

MFE 230G Active Asset Management, final project. Long-short strategy across the
49 Fama-French industries that blends industry price momentum with I/B/E/S
analyst EPS revisions. The full working plan, thesis, and rejection criterion
are in [`CLAUDE.md`](CLAUDE.md).

## Setup

Python 3.9 or newer (tested on 3.9 and 3.11).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

WRDS credentials are never stored in the repo. On first run the `wrds` package
prompts for your password and offers to create `~/.pgpass`. Optionally set
`WRDS_USERNAME` to skip the username prompt.

## Run end to end

| Phase | Command | Output |
|---|---|---|
| 1. Data pulls (WRDS) | `python -m src.pull_wrds` | `data/raw/*.parquet` (not in git) |
| 1. Data pulls (public) | `python -m src.pull_public` | `data/raw/kf_*.parquet`, `fred_macro.parquet` |
| Optional 2026 revision sensitivity | `python -m src.pull_2026_sensitivity && python -m src.sensitivity_2026` | separately flagged sensitivity parquet and coverage CSV |
| 2. Clean and link | `python -m src.clean` | `data/interim/*.parquet`, coverage tables |
| 3. Build signals | `python -m src.signals` | `data/processed/signals.parquet`, coverage tables, MOM–REV correlation figure |
| 4. IC and blend | `python -m src.ic` | IC/horizon tables, orthogonal REV, expanding blend, figures |
| 5. Risk model and holdings | `python -m src.portfolio` | `data/processed/holdings.parquet`, `portfolio_by_month.csv`, `portfolio_risk_summary.csv`, λ figure |
| 6. Backtest and costs | `python -m src.backtest` | `strategy_returns_by_month.csv`, `performance_by_window.csv`, cumulative-return and drawdown figures |
| 7. Factor attribution | `python -m src.attribution` | `factor_regressions.csv`, `alpha_with_without_umd.csv` (needs `kf_ff5`, `kf_umd`, `kf_strev` in `data/raw`) |
| 8. Robustness | not yet implemented | |

Tests: `python -m pytest -q tests`

Pull scripts skip files that already exist; pass `--force` to re-pull.

For source coverage, cleaning decisions, table schemas, formulas, and
interpretation caveats, see
[`docs/data_collection_and_interpretation.md`](docs/data_collection_and_interpretation.md).

## Conventions

- Monthly dates are **month-end timestamps** (last calendar day, `datetime64`),
  set by `src/utils.to_month_end` at load time.
- Returns are decimals; Ken French percent returns are divided by 100 on load,
  and `-99.99` / `-999` become NaN.
- All parameters are in `config.py`.
- `data/raw/` and `data/interim/` are git-ignored (licensed WRDS data).

## Status notes

### Phase 1: data pulls (refreshed 2026-10-03)

- WRDS pulls use the current CRSP CIZ monthly and names tables, I/B/E/S statsum,
  and the I/B/E/S-CRSP link history. CRSP total returns are not adjusted a second
  time with legacy delisting returns.
- Public sources were refreshed from Ken French and FRED. FRED's October 2026
  monthly average is partial because only early-October observations were
  available at pull time.
- WRDS currently serves CRSP monthly observations only through December 2025;
  I/B/E/S statsum runs through August 2026. The link history yields no linked
  ticker-months in 2026, so the cleaned I/B/E/S-CRSP panel ends in December 2025.

| File | Rows | First date | Last date |
|---|---:|---|---|
| ibes_statsum | 2,241,796 | 1985-01-17 | 2026-08-20 |
| ibes_crsp_link | 30,080 | 1976-01-15 | 2025-12-18 (sdate) |
| crsp_msf (CIZ) | 2,880,406 | 1984-01-31 | 2025-12-31 |
| crsp_msenames (CIZ) | 67,929 | 1925-12-31 | 2025-12-31 |
| kf_ind49_vw | 1,202 | 1926-07-31 | 2026-08-31 |
| kf_ff5 | 758 | 1963-07-31 | 2026-08-31 |
| kf_umd | 1,196 | 1927-01-31 | 2026-08-31 |
| kf_strev | 1,207 | 1926-02-28 | 2026-08-31 |
| fred_macro | 605 | 1976-06-30 | 2026-10-31 (partial month) |

CRSP ends 8 months before I/B/E/S statpers. The source did not provide data
through October 2026; do not interpret carried CRSP characteristics as current
prices. The linked panel includes `crsp_date`, `price_age_months`, and a blank
`prc` whenever the attached CRSP observation is carried forward.

### Phases 2–3: cleaning and signals (rebuilt 2026-10-04)

- The cleaned CRSP panel has 2,861,589 stock-months through December 2025. The
  I/B/E/S-linked panel has 1,851,249 firm-months through December 2025. CRSP
  characteristics are no longer carried across missing security-months while
  the overall CRSP panel still covers that period; zero rows are carried in
  the current output.
- I/B/E/S ticker-month link rate is 87.7% in 2025 and 0% in 2026. The full
  coverage grid has 24,500 month-industry cells; 1,037 have fewer than five
  linked firms. All 392 cells from January–August 2026 have zero linked firms.
  Review `ibes_link_rate_by_year.csv` and `ibes_industry_coverage.csv` with the
  team at the Phase 2 checkpoint.
- The MOM window now compounds industry returns from `t-11` through `t-1`.
  The signal panel has 58,898 industry-months through August 2026. MOM is
  available for all 392 2026 rows; REV and REV_ALT are missing for all of them.
  `next_return` is present for 343 rows (January–July 2026); August's
  following-month return is not yet available.
- `signal_coverage_by_month.csv` records monthly available/missing counts.
  `results/figures/mom_rev_correlation.png` contains 492 monthly MOM–REV
  cross-sectional correlations from January 1985 through December 2025.
- An **optional sensitivity only** is stored separately in
  `data/processed/signals_2026_sensitivity.parquet`; it uses exact CUSIP matches
  to one PERMNO at the December 2025 CRSP names reference date, ACTPSUM USD
  prices/shares with a recent pricing date, and December 2025 SIC/industry
  assignments. It has 392 industry-month rows: 373 with REV and 309 with
  REV_ALT. It does not replace or fill the primary `signals.parquet` values.
- **Team decision still pending:** whether `ibcrsphist` links whose `edate` is
  the table's last date may be treated as active beyond that date. No end-date
  extension has been applied. The separate CUSIP sensitivity is not proof that
  all such ticker links remain valid.
- `signal_coverage_by_horizon.csv` reports, for the full sample, post-2010, and
  the planned recent window (March 2025–August 2026, not shifted), how many
  months each signal has and how many are evaluable (signal and next-month
  return both present). Rerun `python -m src.signals` to produce it.

### Phase 4: IC and blend (run 2026-10-04)

- `python -m src.ic` writes `ic_by_month.csv`, `ic_summary_by_horizon.csv`,
  `blend_weights_by_month.csv`, and `data/processed/signals_phase4.parquet`;
  it also saves rolling-IC and blend-weight figures.
- IC uses the primary signal at month `t` against `next_return` at `t+1`.
  REV is residualized against MOM cross-sectionally for the orthogonal test.
  Expanding weights for month `t` use only past paired IC observations and
  signal correlations through `t-1`; at least 60 paired IC months are required.
- In the required recent 18-month window, MOM has 17 evaluable months because
  August 2026 lacks September returns. REV and REV_ALT each have 10 evaluable
  months because primary I/B/E/S links end in 2025. Spearman mean ICs: MOM
  0.0147, REV -0.0100, REV_ALT -0.0042, REV-orthogonal 0.0220, blended 0.0177.
  These are descriptive with limited coverage and should not be treated as
  high-confidence recent evidence.
- Primary 2026 REV remains missing. The CUSIP/ACTPSUM sensitivity remains a
  separate file and is not included in these primary ICs or weights.

### Phase 4 checkpoint: REV-orthogonal IC is near zero (CLAUDE.md 12.4)

Spearman IC, signal month `t` vs. industry return `t+1`. Newey-West t-stats
use 6 lags. `rev_sample` = the 492 months with primary REV (Jan 1985–Dec 2025),
so MOM and REV are compared over the same months.

| Signal | rev_sample mean IC | NW t | post-2010 mean IC | NW t |
|---|---:|---:|---:|---:|
| MOM | 0.047 | 3.96 | 0.035 | 2.22 |
| REV | 0.010 | 1.06 | -0.000 | -0.01 |
| REV_ALT | 0.012 | 1.36 | 0.009 | 0.68 |
| REV orthogonal to MOM | -0.000 | -0.05 | -0.007 | -0.50 |
| Blend | 0.040 | 3.17 | 0.036 | 2.49 |

- **Flag:** once momentum is removed, REV has no predictive power for
  next-month industry returns, in the full REV sample or post-2010. This is
  early evidence against the thesis that revisions carry information beyond
  momentum. The blend's REV weight falls from about 0.35 (1990) to about
  -0.12 (2025), so the blended signal is essentially momentum.
- The rejection criterion is about factor-adjusted alpha net of costs, so
  the project continues to Phases 5–7 as planned and reports the result
  either way (CLAUDE.md 0, 13). The thesis is unchanged.
- The full-window MOM IC (t = 8.5) starts in 1927; compare MOM with REV only
  over `rev_sample`.
- Recent 18 months: 10 evaluable REV months; descriptive only.

### Phase 5: risk model and holdings (rerun 2026-10-04 with shrinkage)

- `src/risk.py`: EWMA covariance of the 49 Ken French industry returns,
  30-month half-life, 60-month minimum, estimated each month from returns
  through that month; residual-to-average industry volatility for omega.
  Returns are rebuilt from `next_return` in the committed signal panel. RF is
  not subtracted: it is common to all industries, so it drops out of risk for
  dollar-neutral books.
- **Team decision:** the covariance is shrunk 50% toward its diagonal for
  optimization, λ, and ex-ante risk (CLAUDE.md 7.1). Without shrinkage the
  mean-variance books hit 5% ex-ante but realized 9–10% with ~4x gross.
- `src/portfolio.py`: Grinold-Kahn alphas, mean-variance holdings with
  dollar neutrality and |h_n| <= 10% of gross (solved as a fixed point), the
  HW02 diagonal comparison, and λ set each month so ex-ante active risk is 5%.
- Choices not fixed by the plan: industries with a missing signal get no
  position that month; the alpha IC is the strategy's own expanding mean IC
  over earlier signal months (60-month minimum, so only its sign matters
  after λ calibration); the diagonal book is demeaned to be dollar neutral
  and has no cap. Beta-neutral holdings are left for the Phase 8 grid.
- Holdings start: MOM June 1974 (first full covariance), REV and REV
  orthogonal January 1990, blend January 1995.

| Strategy (mean-variance) | Ex-ante risk | Realized active vol | Median λ | Mean gross |
|---|---:|---:|---:|---:|
| MOM | 5.0% | 6.2% | 3.8 | 1.2x |
| REV | 5.0% | 4.8% | 1.2 | 1.5x |
| REV orthogonal | 5.0% | 4.3% | 0.33 | 1.5x |
| Blend | 5.0% | 6.6% | 2.3 | 1.2x |

- Realized/target is 0.86–1.32. MOM and the blend run above target mainly
  through momentum crashes (2009).
- REV orthogonal's λ falls toward zero late in the sample because its
  expanding IC is near zero: the optimizer scales up an almost-zero alpha to
  reach 5% risk.

### Phase 6: backtest, turnover, costs (run 2026-10-04)

- `src/backtest.py`: gross return h(t)·r(t+1); turnover against prior
  weights drifted by month-t returns; cost charged on the t+1 return; net
  returns at 10/20/30 bp one-way. Windows by formation month: own full
  history, `common` (Jan 1995–Dec 2025, all four strategies trade), post-2010,
  and the fixed recent 18 months.
- Outputs: `strategy_returns_by_month.csv`, `performance_by_window.csv`,
  `cumulative_net_returns.png`, `blend_drawdown.png`.

Common window (formation Jan 1995–Dec 2025, 372 months), mean-variance:

| Strategy | Gross ann. return | Vol | Gross Sharpe | Monthly turnover | Net Sharpe 10 / 20 / 30 bp | Max DD (20 bp) |
|---|---:|---:|---:|---:|---|---:|
| MOM | 3.9% | 6.6% | 0.59 | 51% | 0.49 / 0.40 / 0.31 | -20% |
| REV | 0.2% | 5.0% | 0.04 | 174% | -0.38 / -0.80 / -1.21 | -72% |
| REV orthogonal | -0.3% | 4.4% | -0.08 | 182% | -0.57 / -1.07 / -1.56 | -78% |
| Blend | 3.2% | 6.6% | 0.48 | 58% | 0.38 / 0.27 / 0.17 | -23% |

- REV has no gross edge, and its industry ranks change a lot month to month
  (rank autocorrelation 0.42 vs. 0.90 for MOM), so it trades ~175% of
  capital a month and loses heavily after costs. The blend is mostly MOM and
  does slightly worse than MOM alone.
- Post-2010 net Sharpe (20 bp): MOM 0.44, blend 0.32, REV -0.68, REV
  orthogonal -0.93. Recent 18 months: 17 return months for MOM, 10 for the
  REV-based strategies; descriptive only.
- No net Sharpe exceeds 1.5 (CLAUDE.md 13 look-ahead check).
- Phase 7 (6-factor alpha with Newey-West t-stats) decides the rejection
  criterion; these Sharpe ratios are not yet factor-adjusted.

### Phase 7: factor attribution (code ready 2026-10-04; run on a machine with `data/raw`)

- `src/attribution.py` regresses monthly net returns (20 bp) on FF5 + UMD
  (primary), FF5 alone (with/without-UMD comparison), and FF5 + UMD + ST
  reversal, with Newey-West (6-lag) t-stats, for every strategy, method, and
  window (full, common, post-2010, recent 18 months).
- Each return month t+1 is matched to factor returns of month t+1; the run
  stops if any return month is missing from the factor data.
- `alpha_with_without_umd.csv` has `passes_criterion` = yes only when the
  6-factor net alpha is positive with t >= 2 (CLAUDE.md 0).
- Tested on synthetic factors only. Results: TBD after
  `python3 -m src.attribution`.
