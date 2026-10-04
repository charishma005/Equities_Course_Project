# MFE 230G Final Project — Industry Analyst Revisions vs. Industry Momentum

This file is the working plan for the project. Read it fully before writing any code.
Work through the phases in order. Each phase lists tasks, outputs, and acceptance checks.
Do not move to the next phase until the acceptance checks for the current one pass.

---

## 0. Project summary

**Course:** MFE 230G Active Asset Management, final group project.

**Strategy:** A long-short portfolio across the 49 Fama-French industries, built from two
signals: (1) industry price momentum and (2) industry-level analyst EPS estimate revisions
(from I/B/E/S). Signals are blended using IC-based weights, converted to alphas, and sized
with a mean-variance optimizer on an EWMA covariance matrix.

**Thesis (falsifiable, fixed before testing):**
Earnings news diffuses slowly, so industries with net upward analyst estimate revisions
outperform over the following month, and this revision signal carries information beyond
price momentum.

**Rejection criterion (decided in advance):**
If the revision signal (or the blended strategy) shows no statistically significant alpha
(|t| < 2) after controlling for FF5 + UMD, net of costs, and particularly in the post-2010
sample, the report concludes **"do not implement."** A negative result is acceptable and
must be reported honestly.

**Core research question:** Does the analyst-revision signal add alpha beyond momentum
(UMD), or is it repackaged momentum?

---

## 1. Ground rules (apply to every phase)

### 1.1 No look-ahead bias — the most important rule
- A signal formed at the end of month `t` may only use information available on or before
  the end of month `t`. It predicts the return in month `t+1`.
- I/B/E/S `statpers` is the snapshot date (usually the third Thursday of the month). For
  month-end `t`, use the latest `statpers` that is `<=` the last calendar day of month `t`.
- Covariance matrices, IC estimates, blend weights, and λ calibration must use only data
  up to month `t` (expanding or rolling windows). Never fit anything on the full sample
  and then apply it in-sample.
- CRSP SIC codes and market caps must be as of month `t`, not current values.
- Write an explicit test for each signal: shift the signal forward by one month and confirm
  the merge with returns lines up `signal[t]` with `return[t+1]`.

### 1.2 Data handling and licensing
- Raw WRDS data (I/B/E/S, CRSP) is licensed to the university. **Never commit raw WRDS
  files to git.** `data/raw/` and `data/interim/` must be in `.gitignore`.
- Never hardcode WRDS credentials. Use the `wrds` Python package with a `~/.pgpass` file,
  or prompt at runtime.
- Save pulls as parquet (compressed). Pull once, then work from local files.
- Processed industry-level panels (49 industries × months) are small and may be saved to
  `data/processed/`.

### 1.3 Code conventions
- Python 3.11+, pandas, numpy, statsmodels, scipy, matplotlib, pyarrow, wrds.
- Monthly frequency throughout. Use month-end `Period('M')` or month-end timestamps
  consistently; pick one and convert everything to it at load time.
- Returns in decimals (0.01 = 1%) internally; convert Ken French percent returns on load.
- Every function has a docstring stating inputs, outputs, and timing convention.
- All parameters (lookbacks, half-life, cost levels, λ target, date splits) live in
  `config.py`, never as magic numbers in the code.
- Every plot: title, labeled axes with units, sample period in the title or caption,
  legend when there is more than one series. Save to `results/figures/` as PNG (dpi 200).
- Every table: saved as CSV in `results/tables/`, with units in column names.

### 1.4 AI interaction log (course requirement)
The project requires at least three documented GenAI interactions (idea generation, coding,
robustness design). Work done in Claude Code counts. For each substantial interaction:
- Append an entry to `ai_log/ai_interactions.md` with: date, phase, the prompt verbatim,
  and a 3–5 sentence summary of what was produced.
- Leave a section titled **"Critical evaluation (to be written by the team)"** empty.
  Do not write the evaluation yourself; the team writes it.
- If a bug or wrong assumption in AI-generated code is found later (especially look-ahead
  bias), add a note to the relevant log entry describing what was wrong and how it was
  fixed. These cases are the most valuable part of the AI section.

---

## 2. Repository structure

```
project/
├── CLAUDE.md                  # this file
├── README.md                  # how to run end to end
├── config.py                  # all parameters
├── .gitignore                 # data/raw, data/interim, .env, __pycache__
├── data/
│   ├── raw/                   # WRDS pulls + Ken French downloads (NOT in git)
│   ├── interim/               # cleaned stock-level files (NOT in git)
│   └── processed/             # industry-level panels (small, OK in git)
├── src/
│   ├── pull_wrds.py           # Phase 1: I/B/E/S, link table, CRSP
│   ├── pull_public.py         # Phase 1: Ken French + FRED
│   ├── clean.py               # Phase 2: merges, industry mapping
│   ├── signals.py             # Phase 3: momentum + revision signals
│   ├── ic.py                  # Phase 4: IC analysis + blending
│   ├── risk.py                # Phase 5: EWMA covariance
│   ├── portfolio.py           # Phase 5: alphas -> holdings, λ calibration
│   ├── backtest.py            # Phase 6: returns, turnover, costs
│   ├── attribution.py         # Phase 7: factor regressions
│   ├── robustness.py          # Phase 8: horizon splits + parameter grid
│   └── plots.py               # shared plotting helpers
├── tests/
│   └── test_timing.py         # look-ahead and alignment tests
├── notebooks/                 # exploration only; final logic lives in src/
├── results/
│   ├── figures/
│   └── tables/
└── ai_log/
    └── ai_interactions.md
```

---

## 3. Phase 1 — Data pulls

### 3.1 I/B/E/S Summary Statistics
- **Table:** `ibes.statsum_epsus`
- **Columns:** `ticker, cusip, statpers, fpedats, numest, numup, numdown, meanest, medest, stdev`
- **Filters:** `measure = 'EPS'`, `fiscalp = 'ANN'`, `fpi = '1'`, `usfirm = 1`,
  `statpers >= '1985-01-01'`
- **Output:** `data/raw/ibes_statsum.parquet`

### 3.2 I/B/E/S–CRSP link
- **Table:** `wrdsapps.ibcrsphist`
- **Columns:** `ticker, permno, sdate, edate, score`
- **Filter:** keep `score <= 2`
- **Output:** `data/raw/ibes_crsp_link.parquet`

### 3.3 CRSP
- `crsp.msf_v2`: `permno, mthcaldt, mthret, mthprc, shrout` from 1984-01-01;
  filter to common equity (`EQTY`/`COM`/`NS`) on NYSE, AMEX, or Nasdaq.
- `crsp.stocknames_v2`: historical names and SIC codes, filtered to the same universe.
- `mthret` is CRSP's monthly total return; do not apply a separate legacy delisting
  return on top of it.
- **Output:** normalized `data/raw/crsp_msf.parquet` and `crsp_msenames.parquet`.
- **Check:** print the max CRSP date and compare it with I/B/E/S; record any gap in
  `README.md` (see 4.4).

### 3.4 Ken French Data Library (public)
- 49 Industry Portfolios, value-weighted, monthly (`49_Industry_Portfolios`)
- Industry SIC definitions (`Siccodes49`)
- Fama/French 5 Factors 2x3, monthly (includes RF)
- Momentum Factor (UMD), monthly
- Short-Term Reversal Factor, monthly (used as a robustness regressor)
- Use `pandas_datareader` (`famafrench`) or download the CSV zips directly.
- Watch out: Ken French files use `-99.99` / `-999` as missing and report percent returns.

### 3.5 FRED (optional, for macro extension in Phase 8)
- `BAA10Y` (credit spread), `T10Y2Y` (term spread). Monthly averages, lagged one month.

### Acceptance checks
- Row counts and date ranges printed and recorded in `README.md`.
- No raw files tracked by git (`git status` clean for `data/raw`).

---

## 4. Phase 2 — Cleaning and industry mapping

### 4.1 CRSP stock universe
- Keep CIZ common equity (`EQTY`/`COM`/`NS`) on NYSE, AMEX, or Nasdaq, using the names
  record valid at each date (`namedt <= date <= nameendt`).
- Market cap = `abs(prc) * shrout` (in $ thousands).
- Use CIZ `mthret` as the monthly total return; it must not be combined again with
  legacy delisting returns.

### 4.2 Map stocks to the 49 industries
- Parse `Siccodes49` into SIC ranges → industry code.
- Map each stock-month's historical `siccd` (from `msenames`, as of that month).
- Stocks with SIC codes outside all ranges go to "Other" (industry 49), matching
  Ken French's convention.

### 4.3 Link I/B/E/S to CRSP
- Join I/B/E/S on `ticker` to the link table where `sdate <= statpers <= edate`.
- Convert `statpers` to its month (the month containing the snapshot). Per 1.1, the
  snapshot in month `t` is used for the signal at the end of month `t`.
- If a ticker has multiple `statpers` in a month, keep the latest.
- Attach end-of-month-`t` market cap and industry from CRSP.

### 4.4 CRSP coverage gap
- Only for months after the dataset-wide CRSP end date, carry the last available market
  cap and SIC per PERMNO (max 12 months), and flag those months. Within CRSP's covered
  period, do not carry across a security-specific missing month. Do not carry forward
  `prc`; set it missing and expose `crsp_date` and `price_age_months`. State this
  limitation in the report's data section.
- Industry **returns** always come from Ken French's 49 industry portfolios, which are
  updated monthly, so the return side has no gap.
- **Team decision (2026-10):** `wrdsapps.ibcrsphist` updates annually and has no links
  valid in 2026, so primary REV and REV_ALT are missing from January 2026 on. Keep them
  missing: never zero-fill them or substitute sensitivity values. MOM continues through
  the last Ken French month. Any 2026 revision results built with a different matching
  or price source (e.g., CUSIP links, `ibes.actpsum_epsus` prices) are an exploratory
  sensitivity only, reported separately and labeled with their source.

### Output
- `data/interim/ibes_crsp_monthly.parquet`: one row per (permno, month) with
  `numest, numup, numdown, meanest, mktcap, industry`.

### Acceptance checks
- Share of I/B/E/S firm-months successfully linked, by year (save as a table).
- Number of covered firms per industry per month; flag industry-months with < 5 firms.

---

## 5. Phase 3 — Signal construction

All signals are formed at the end of month `t`, cross-sectionally across the 49 industries.

### 5.1 Industry momentum (MOM)
- Cumulative return over months `t-11` through `t-1`, excluding the signal month `t`,
  from Ken French value-weighted industry returns.
- Parameters in config: `MOM_LOOKBACK = 12`, `MOM_SKIP = 1`.

### 5.2 Industry analyst revisions (REV) — main specification
- Firm level: `rev_i = (numup - numdown) / numest`, requiring `numest >= 3`.
- Industry level: market-cap-weighted mean of `rev_i` across firms in the industry,
  using caps at end of month `t`.
- Require at least 5 covered firms; otherwise the industry's REV is missing that month.

### 5.3 REV alternative (robustness)
- Firm level: `(meanest_t - meanest_{t-3}) / |price_t|`, same fiscal period end
  (`fpedats` unchanged) only. Require `numest >= 3` in both snapshots and a current,
  nonzero CRSP price. Winsorize at 1st/99th percentile each month.
- Aggregate to industry the same way as 5.2.

### 5.4 Standardization
- Each month, z-score each signal across available industries, then winsorize at ±3.
- Preserve missing industry values as missing; do not interpret unavailable data as neutral.
- If all values for a signal are missing in a month, leave all standardized values missing.
- Record monthly coverage and missing counts in `signal_coverage_by_month.csv`.

### Output
- `data/processed/signals.parquet`: (month, industry, mom_z, rev_z, rev_alt_z).
- Figure: `results/figures/mom_rev_correlation.png`, monthly cross-sectional Pearson
  correlation between MOM and REV across available industries.

### Acceptance checks
- `tests/test_timing.py` passes: momentum uses returns through `t-1`, and signals at `t`
  are aligned with returns at `t+1`.
- Summary stats of each signal (mean, std, coverage) saved as a table.

---

## 6. Phase 4 — IC analysis and signal blending

### 6.1 Information coefficients
- Monthly IC = Spearman rank correlation between signal z-scores at `t` and industry
  returns at `t+1`. Also compute Pearson as a check.
- Report for each signal: mean IC, std of IC, IC t-stat, IC information ratio,
  % of months with IC > 0, valid IC month count, and industry-month pair count.
- Report for full sample, post-2010, and the most recent 18 months.
- For each window also report requested months, months with any raw signal,
  evaluable IC months, and industry-months with signal coverage. Keep the recent
  window fixed to the most recent 18 signal months even when REV is missing.
- Figure: 12-month rolling mean IC for MOM and REV on one chart.

### 6.2 Incremental information
- Regress REV z-scores on MOM z-scores each month; the residual is the part of REV
  orthogonal to momentum. Compute its IC. This is a direct test of the thesis.
- Preserve missing industries. Require at least `IC_MIN_INDUSTRIES` paired
  signal/return observations to calculate a monthly IC.

### 6.3 Blending (HW02 method)
- `w ∝ R^{-1} · IC`, where `R` is the correlation matrix of the two signals and `IC` is the
  vector of mean ICs.
- Estimate `R` and `IC` on an **expanding window using information observable by
  month `t` only**: paired ICs and cross-signal correlations from signal months
  strictly before `t`. Require 60 joint MOM/REV IC months before the first blend.
- Normalize weights to sum to 1. Blended score = `w_mom * mom_z + w_rev * rev_z`,
  re-standardized cross-sectionally only where both signals are available.
- Figure: blend weights over time.
- Outputs: `results/tables/ic_by_month.csv`,
  `results/tables/ic_summary_by_horizon.csv`,
  `results/tables/blend_weights_by_month.csv`, and
  `data/processed/signals_phase4.parquet`.

### Acceptance checks
- Blend weights at month `t` depend only on data through `t` (test that changing
  month-`t` or future returns cannot change month-`t` weights).
- Table: IC statistics for MOM, REV, REV-orthogonal, and blended signal.

---

## 7. Phase 5 — Risk model and portfolio construction

### 7.1 EWMA covariance (HW01 method)
- Covariance of the 49 industry excess returns, exponentially weighted with a
  **30-month half-life**, estimated each month on data through month `t` only.
- Minimum history: 60 months.
- Annualize volatilities by `sqrt(12)`.
- **Team decision (2026-10-04):** shrink the EWMA covariance 50% toward its diagonal
  (`COV_SHRINKAGE = 0.5`) for optimization, λ calibration, and ex-ante risk. With the
  unshrunk matrix, ex-ante risk hit 5% but realized active volatility of the
  mean-variance books was about 10% with ~4x gross exposure. `omega` in 7.2 uses the
  unshrunk EWMA. The unshrunk model (`COV_SHRINKAGE = 0`) remains a robustness case.

### 7.2 Alphas
- Grinold-Kahn: `alpha_n = IC * omega_n * z_n`, where `IC` is the expanding-window
  blended IC and `omega_n` is industry `n`'s volatility (residual to the equal-weighted
  industry average) from the covariance matrix.
- Remove the cross-sectional mean so alphas are dollar neutral.

### 7.3 Holdings
- Mean-variance active holdings: `h = (1 / 2λ) · Σ^{-1} α`, subject to:
  - dollar neutral: `sum(h) = 0`
  - optional market-beta neutral (robustness)
  - per-industry position cap: `|h_n| <= 10%` of gross
- Solve with `scipy.optimize` (or cvxpy if available).
- Also implement the diagonal version `h_n = α_n / (2λ ω_n²)` from HW02 as a comparison.

### 7.4 λ calibration
- Choose λ each month so ex-ante active risk `sqrt(h' Σ h)` equals the target
  (`TARGET_ACTIVE_RISK = 0.05` annualized). Report the implied λ over time.
- The report must state λ and the active risk it implies.

### Acceptance checks
- Ex-ante active risk equals target each month (within tolerance).
- Realized annualized active volatility reported and compared with the 5% target.

---

## 8. Phase 6 — Backtest, turnover, and costs

- Strategy return in month `t+1` = `sum_n h_n(t) * r_n(t+1)` using Ken French industry
  returns (excess of RF for the long-short book; note dollar-neutral books don't need RF).
- Turnover at `t` = `sum_n |h_n(t) - h_n(t-1)·drift|` where drift adjusts prior weights
  for realized returns.
- Net return = gross − turnover × cost, for one-way costs of **10, 20, and 30 bps**.
- Run four strategies: MOM only, REV only, REV orthogonal, BLENDED.

### Outputs
- Table per strategy: annualized return, volatility, Sharpe, max drawdown,
  average monthly turnover, net Sharpe at each cost level.
- Figure: cumulative net returns (20 bps) for all four strategies, log scale.
- Figure: drawdowns of the blended strategy.

---

## 9. Phase 7 — Factor attribution (alpha vs. beta)

- Regress monthly **net** returns (20 bps base case) of each strategy on:
  **Mkt-RF, SMB, HML, RMW, CMA, UMD** (6 factors).
- Robustness specification: add the Short-Term Reversal factor (7 factors).
- Use Newey-West standard errors with 6 lags.
- Report: annualized alpha (×12), alpha t-stat, each loading with t-stat, R².
- Key comparison table: alpha of REV and BLENDED with vs. without UMD in the regression.
- Run for full sample, post-2010, and most recent 18 months (note low power in the
  short window; report it anyway).

### Acceptance checks
- Factor data and strategy returns aligned on the same months (assert no off-by-one).

---

## 10. Phase 8 — Horizons and robustness

### 10.1 Required horizon splits (report all three, even if results are bad)
- Full sample (first signal month to latest)
- Post-2010 (2010-01 onward)
- Most recent 18 months (the last 18 signal months; with data through August 2026 this
  is March 2025–August 2026). Do not shift the window to where coverage is complete;
  report how many months each signal actually covers and can be evaluated (signal and
  next-month return both present) in each window.

### 10.2 Parameter grid (blended strategy unless noted)
| Dimension | Values |
|---|---|
| Momentum lookback | 6, 9, 12 months |
| Revision measure | net-revision ratio (main), consensus change (alt) |
| Min analysts per firm | 1, 3, 5 |
| Covariance half-life | 18, 30, 60 months |
| Active risk target | 3%, 5%, 8% |
| Costs (one-way) | 10, 20, 30 bps |
| Industry set | 49 vs. 30 industries |
| Neutrality | dollar-neutral vs. dollar + beta-neutral |

- Output: one table of net Sharpe and 6-factor alpha t-stat across the grid.
- Figure: heatmap of net Sharpe over (momentum lookback × half-life).

### 10.3 Subperiod stability
- Rolling 36-month alpha (6-factor) for the blended strategy.
- Annual returns by year (bar chart) to show whether returns are concentrated in one regime.
- Specifically examine 2009 (momentum crash) and 2020.

### 10.4 Optional macro extension
- Scale exposure down (e.g., by 50%) when the lagged credit spread is above its expanding
  median. Compare alpha and drawdowns with the unconditioned strategy.

---

## 11. Phase 9 — Report assets

Generate everything the report needs into `results/`. The report template is fixed:
1. **Executive Summary** (1 paragraph; written last; must state implement / do not implement)
2. **What Did You Try?** (2–5 pages): thesis, data (sample, frequency, weighting,
   survivorship and revision handling), signal construction, risk model, sizing, λ
3. **What Did You Learn?** (1–4 pages): factor exposures, time patterns, robustness,
   evaluation of the AI's role
4. **Appendices:** AI transcripts with evaluations, full tables and plots, code snippets

Create `results/summary.md` that collects the key numbers in one place:
- IC table (Phase 4)
- Performance table (Phase 6)
- 6-factor regression table (Phase 7)
- Horizon split table (Phase 8)
- Robustness grid (Phase 8)
- List of all figures with one-line captions

---

## 12. Order of work and checkpoints

1. Phase 1 (data pulls) → commit code only.
2. Phase 2 (cleaning) → review link rates and coverage tables with the team.
3. Phase 3 (signals) → timing tests must pass.
4. Phase 4 (IC) → **checkpoint:** if REV-orthogonal IC is near zero, flag it early.
   The project can still proceed toward a "do not implement" conclusion.
5. Phases 5–7 → full backtest and attribution.
6. Phase 8 → robustness.
7. Phase 9 → report assets.

At each checkpoint, write a short status note in `README.md`: what was done, key numbers,
anything suspicious.

---

## 13. Things to stop and ask the team about

- Any result that looks too good (e.g., net Sharpe > 1.5, IC > 0.10): check for
  look-ahead before reporting.
- Any design choice not specified here.
- Any data access problem with WRDS.
- Any temptation to change the thesis or rejection criterion after seeing results:
  don't. Record the result and keep the original thesis.
