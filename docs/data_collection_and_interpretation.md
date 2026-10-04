# Data Collection and Interpretation Guide

This guide describes the data currently collected for the industry momentum and
analyst-revision project, how the source tables are cleaned and joined, what the
sample tables represent, and how to interpret their fields. Coverage figures
Input-pull coverage below reflects the refresh run on **October 3, 2026**;
cleaning and signal outputs were rebuilt on October 4 after the documented
method corrections. Provider coverage can change on later pulls.

## 1. Pipeline at a Glance

The data flow is:

1. Pull licensed firm-level data from WRDS and public market/factor data from
   Ken French and FRED into `data/raw/`.
2. Clean CRSP and link monthly I/B/E/S snapshots to valid CRSP securities in
   `src/clean.py`; save stock-month and linked firm-month panels to
   `data/interim/`.
3. Build industry signals and their next-month return outcomes in
   `src/signals.py`; save `data/processed/signals.parquet`.

Exploration notebooks, if any, belong in `notebooks/`; they only inspect these
files and never create the signal table.

### Commands

From the project directory, activate the project environment and run:

```bash
source .venv/bin/activate
python -m src.pull_wrds --force
python -m src.pull_public --force
python -m src.clean
python -m src.signals
# Optional sensitivity only; does not change signals.parquet
python -m src.pull_2026_sensitivity
python -m src.sensitivity_2026
python -m src.ic
```

WRDS requires an active university account and credentials. Credentials are not
stored in the repository. Pulls without `--force` skip files that already
exist. Raw WRDS data is licensed and should remain untracked; `data/raw/` and
`data/interim/` are ignored by git.

## 2. Sources and Current Coverage

### WRDS

- `ibes.statsum_epsus`: annual U.S. EPS summary statistics, filtered to
  `measure='EPS'`, `fiscalp='ANN'`, `fpi='1'`, `usfirm=1`, with `statpers` from
  1985 onward. The pull contains 2,241,796 rows, from January 17, 1985 through
  August 20, 2026.
- `wrdsapps.ibcrsphist`: historical ticker-to-PERMNO links with score at most
  2; 30,080 link records were pulled. A ticker-month is accepted only when its
  link is valid on that row's `statpers` date.
- `crsp.msf_v2` and `crsp.stocknames_v2`: current CRSP CIZ monthly returns,
  prices, shares, and historical security/name data. The pull contains
  2,880,406 monthly rows from January 1984 through December 2025.
- Optional sensitivity: `ibes.actpsum_epsus` provides `price`, `prdays`,
  `shout` (shares outstanding in millions), and `curr_price`. The sensitivity
  pull filters to 2026 onward, `measure='EPS'`, and `usfirm=1`.

The query has no December 2025 end-date filter. December 2025 is the latest
monthly CRSP date returned by WRDS for the account and tables used in this run.
I/B/E/S extends into 2026, but the current link history yields no linked
I/B/E/S firm-months in 2026. The linked firm-month panel therefore ends in
December 2025. Do not fill this gap with invented or forward-dated prices.
The sensitivity instead uses the ACTPSUM price/shares and exact CUSIP matches
to the CRSP names record valid on the final available CRSP date. It is a
separate robustness view, not an extension of the primary `ibcrsphist` links.

### Public data pulled by the project

- `kf_ind49_vw.parquet`: value-weighted monthly returns for 49 Fama-French
  industries, July 1926 through August 2026.
- `kf_ind30_vw.parquet`: 30-industry alternative for robustness.
- `kf_sic49.parquet` and `kf_sic30.parquet`: SIC-code ranges and names used to
  map companies into the corresponding Fama-French industry groups.
- `kf_ff5.parquet`: monthly `Mkt-RF`, `SMB`, `HML`, `RMW`, `CMA`, and `RF`,
  July 1963 through August 2026.
- `kf_umd.parquet`: monthly momentum factor `UMD`, January 1927 through
  August 2026.
- `kf_strev.parquet`: monthly short-term reversal factor, February 1926 through
  August 2026.
- `fred_macro.parquet`: monthly average `BAA10Y` and `T10Y2Y` series. Its
  October 2026 month-end row is partial because the pull occurred on October 3.

Ken French returns are converted from percent to decimal units; source missing
codes `-99.99` and `-999` become missing values. FRED series are monthly means
in the units published by FRED and are not lagged at pull time. Apply the
configured lag when using them in a model. Do not treat the partial October
2026 FRED value as a completed monthly observation.

## 3. What the Samples Represent

| Table | Granularity | Current size and date coverage |
|---|---|---|
| `data/raw/ibes_statsum.parquet` | Ticker and analyst snapshot / fiscal period | 2,241,796 rows; 1985-01-17 to 2026-08-20 |
| `data/raw/crsp_msf.parquet` | PERMNO and CRSP month | 2,880,406 rows; 1984-01-31 to 2025-12-31 |
| `data/interim/crsp_monthly.parquet` | Eligible PERMNO and month | 2,861,589 rows; 1984-01-31 to 2025-12-31 |
| `data/interim/ibes_crsp_monthly.parquet` | Linked PERMNO and I/B/E/S month | 1,851,249 rows; 1985-01-31 to 2025-12-31 |
| `data/processed/signals.parquet` | Fama-French industry and signal month | 58,898 rows; 1926-07-31 to 2026-08-31 |
| `data/processed/signals_2026_sensitivity.parquet` | 2026 CUSIP/ACTPSUM sensitivity by industry-month | 392 rows; 2026-01-31 to 2026-08-31 |

The signal table has 49 industry rows per month, including months when a
particular signal is missing. Its 58,898 rows cover 1,202 months. The raw
momentum field is present in 55,481 rows; raw REV in 22,387; raw alternative REV
in 20,330; and `next_return` in 55,990. These counts differ because the signals
have different lookback and data-coverage requirements. Monthly counts are
saved in `results/tables/signal_coverage_by_month.csv`.
The separate sensitivity has 373 nonmissing `rev_sens` cells and 309 nonmissing
`rev_alt_sens` cells; these do not fill the missing REV values in the primary
signal table.

### Example: AAPL linked firm-months

| Month | Snapshot (`statpers`) | Fiscal period end (`fpedats`) | Estimates | Up | Down | Mean EPS estimate | CRSP price |
|---|---|---|---:|---:|---:|---:|---:|
| 2025-11-30 | 2025-11-20 | 2026-09-30 | 38 | 32 | 5 | 8.27 | 278.85 |
| 2025-12-31 | 2025-12-18 | 2026-09-30 | 42 | 5 | 3 | 8.25 | 271.86 |

Both rows concern the same fiscal period, but different monthly snapshots. The
up/down counts describe estimate revisions; they do not dictate the direction
of the stock price. The consensus EPS estimate moved from 8.27 to 8.25 while
the price also changed. These fields measure different things.

## 4. Cleaning and Linking

### CRSP stock-month panel

`src/clean.py` performs these operations:

- Normalize CRSP dates to calendar month-end and identifiers to numeric PERMNOs.
- Keep CIZ common equity (`EQTY` / `COM` / `NS`) listed on NYSE, AMEX, or
  Nasdaq. Match the historical name/SIC record valid on each CRSP date.
- Keep only name records valid for that date. Map historical SIC codes to
  Fama-French 49 industries; unmatched SIC codes map to `Other` (industry 49).
- Set market capitalization to `abs(prc) * shrout`. CRSP shares outstanding
  are in thousands, so market capitalization is in thousands of dollars.
- Use CIZ `mthret` as the monthly total return. Do not add legacy delisting
  returns a second time.
- Deduplicate to one record per PERMNO and month.

### I/B/E/S-linked firm-month panel

- Convert `statpers` to its calendar month-end. If a ticker has multiple
  snapshots in a month, retain the latest snapshot.
- Join ticker to PERMNO only when the link is valid on the actual `statpers`
  date and its score is at most 2; among valid candidates prefer the lower
  score.
- Backward-as-of join CRSP characteristics by PERMNO and month. Within the
  overall CRSP coverage period, a security-specific missing month is dropped;
  it is not filled from that security's previous record. Only months after the
  dataset-wide CRSP end date may carry market cap and SIC/industry for at most
  12 months, with a flag. The price itself is **not** carried: `prc` is missing
  when the linked CRSP observation is from an earlier month. `crsp_date` and
  `price_age_months` expose the match date and age.
- The output is deduplicated to one record per PERMNO and month.

### Signal panel

- Use only Ken French 49-industry returns for industry momentum and
  `next_return`; CRSP stock returns are not aggregated for this signal panel.
- Map industry names in Ken French's wide return table to numeric SIC-range
  industry IDs.
- Preserve unavailable signal values as missing. Standardization no longer
  turns missing values into zeros.
- Save monthly valid/missing counts and a MOM–REV correlation figure.

## 5. Column Dictionary and Formulas

### `crsp_monthly.parquet`

| Column | Meaning / calculation | How to interpret |
|---|---|---|
| `permno` | CRSP permanent security identifier | Use this for stable security-level joins; tickers can change. |
| `date` | CRSP monthly date normalized to calendar month-end | Observation month. |
| `ret` | CIZ monthly total return (`mthret`) | Decimal return: `0.05` means 5%. Extreme returns should be investigated, not automatically clipped. |
| `prc` | CRSP monthly price as reported | A price level, not a return. Absolute price is used for market cap. |
| `mktcap` | `abs(prc) * shrout` | Market cap in thousands of dollars. |
| `siccd` | Historical SIC code from the valid names record | Used to assign an industry. |
| `industry` | SIC mapped to the 49-industry classification | Numeric industry ID; 49 is Other. |
| `crsp_carried` | False for observed CRSP stock-month rows | In the linked panel this instead flags a carried CRSP match. |

### `ibes_crsp_monthly.parquet`

| Column | Meaning / calculation | How to interpret |
|---|---|---|
| `permno` | Linked CRSP security identifier | Stable security-level identity. |
| `month` | Month-end of the I/B/E/S snapshot month | Signal information date. |
| `statpers` | I/B/E/S statistics period/snapshot date | The actual date the estimate summary was observed. |
| `ticker` | I/B/E/S ticker | Vendor identifier used for the historical link. |
| `fpedats` | Fiscal period end date for the estimate | Identifies which fiscal period the consensus concerns. Compare estimate changes only for the same fiscal period. |
| `numest` | Number of estimates in the consensus | Used for analyst-coverage thresholds. |
| `numup` | I/B/E/S “Number Up” count | Upward estimate revisions; not guaranteed to be a disjoint subset of `numest`. |
| `numdown` | I/B/E/S “Number Down” count | Downward estimate revisions; do not infer all remaining estimates were unchanged. |
| `meanest` | Mean analyst EPS estimate | Consensus EPS level for `fpedats`; a single level does not say whether expectations are rising. |
| `prc` | Same-month CRSP price when available | Missing if the linked CRSP price is stale or unavailable. |
| `mktcap` | `abs(prc) * shrout` from CRSP | Used as industry aggregation weight; may be carried with the limited CRSP-gap policy. |
| `industry` | Historical SIC mapped to a Fama-French 49 industry | Industry at the CRSP match date. |
| `crsp_date` | Date of the attached CRSP observation | Compare to `month` to determine whether characteristics were carried. |
| `price_age_months` | Calendar-month difference: `month - crsp_date` | Zero means a same-month CRSP record; positive values indicate an older match. |
| `crsp_carried` | True when the CRSP match predates the I/B/E/S month | Treat carried market cap/industry as lower-confidence; price is blank. |
| `score` | WRDS I/B/E/S-CRSP link score | Only scores at most 2 are retained; lower valid scores are preferred. |

### `signals.parquet`

Each row is one industry at the end of `month`.

| Column | Formula / source | How to interpret |
|---|---|---|
| `month` | Month-end signal date `t` | Information is aligned to the end of this month. |
| `industry` | Numeric Fama-French 49 industry ID | Values 1–49; 49 is Other. |
| `mom` | `product(1 + R[i,t-k]) - 1` for `k=1,...,11` | Compound the 11 industry returns from `t-11` through `t-1`; the signal month `t` itself is excluded. |
| `rev` | Market-cap-weighted mean of firm `(numup - numdown) / numest` | Main revision-breadth signal. A firm needs at least 3 estimates; an industry needs at least 5 contributing firms. The ratio is not assumed to be bounded by ±1 because revision counts need not partition current estimates. |
| `rev_firms` | Distinct contributing PERMNO count for `rev` | If fewer than 5 firms contribute, `rev` is missing for that industry-month. |
| `rev_alt` | Market-cap-weighted mean of firm `(meanest[t] - meanest[t-3]) / abs(prc[t])` | Alternative consensus-change signal. Both snapshots must have at least 3 estimates and the same `fpedats`; current price must be present and nonzero. Firm values are winsorized monthly at the 1st/99th percentiles before industry aggregation; at least 5 firms are required. |
| `rev_alt_firms` | Distinct contributing PERMNO count for `rev_alt` | Coverage count for the alternative signal; values below 5 do not produce an industry signal. |
| `mom_z` | Monthly cross-industry z-score of `mom`, clipped to [-3, 3] | Relative momentum versus other industries that month. Missing `mom` stays missing. |
| `rev_z` | Monthly cross-industry z-score of `rev`, clipped to [-3, 3] | Relative revision breadth. Missing `rev` stays missing. |
| `rev_alt_z` | Monthly cross-industry z-score of `rev_alt`, clipped to [-3, 3] | Relative consensus-change signal. Missing `rev_alt` stays missing. |
| `next_return` | Ken French return for this industry in month `t+1` | Evaluation outcome, not an input to the signal. The final available signal month usually has no next-month return yet. |

For each z-score, the mean and standard deviation are computed across available
industries within that month. If a month's available values are all identical,
those observed values receive zero; missing industries remain missing. A zero
is therefore a real standardized neutral value only when the corresponding raw
signal is present.

### `signals_2026_sensitivity.parquet` (optional; not primary)

This separate file keeps the 2026 ACTPSUM/CUSIP method visible rather than
silently mixing it into `signals.parquet`.

| Column | Meaning | Interpretation |
|---|---|---|
| `month`, `industry` | Month-end and numeric Fama-French industry ID | One row for every industry and each of the eight 2026 months. |
| `rev_sens`, `rev_sens_firms` | Main market-cap-weighted revision and contributing firm count | Uses `(numup - numdown) / numest`; market cap is ACTPSUM price × shares. Requires at least 3 estimates per firm and 5 firms per industry. |
| `rev_alt_sens`, `rev_alt_sens_firms` | Three-month same-fiscal-period consensus change divided by current ACTPSUM price, and contributing firm count | Requires at least 3 analysts in both snapshots, a valid current price, and 5 firms per industry. |
| `rev_sens_z`, `rev_alt_sens_z` | Monthly cross-industry z-scores clipped to ±3 | Missing values stay missing. |
| `sensitivity_only` | Always true | Identifies this as a non-primary analysis. |
| `link_method` | `exact_cusip_unique_permno` | CUSIP must map to exactly one PERMNO in the CRSP reference snapshot; `ibcrsphist` dates are not extended. |
| `price_source` | `ibes.actpsum_epsus` | Price must be USD, positive, and dated on/before `statpers` within 31 days. |
| `market_cap_source` | ACTPSUM price × `shout` | `shout` is shares outstanding in millions, so weights use USD millions. |
| `industry_source` | SIC from CRSP names at the reference date, carried into 2026 | This carries the last observed SIC for the sensitivity only. |
| `crsp_reference_date` | Latest CRSP date used for the CUSIP/SIC mapping | Currently December 31, 2025. |

The matching is conservative: unmatched CUSIPs, multiple-PERMNO CUSIPs,
ACTPSUM/estimate CUSIP disagreements, non-USD prices, and missing, nonpositive,
or stale price/share data are excluded. The primary signal table is unchanged.

### Other public table columns

- `kf_ind49_vw` / `kf_ind30_vw`: `date` plus one decimal monthly return column
  per industry.
- `kf_sic49` / `kf_sic30`: `industry`, short label, full name, `sic_lo`, and
  `sic_hi`; the SIC bounds define the industry mapping.
- `kf_ff5`: `Mkt-RF` (market excess return), `SMB`, `HML`, `RMW`, `CMA`, and
  `RF` (risk-free return), all in decimals.
- `kf_umd`: monthly momentum factor return. `kf_strev`: monthly short-term
  reversal factor return.
- `fred_macro`: `BAA10Y` (Moody's Baa corporate yield less 10-year Treasury
  yield) and `T10Y2Y` (10-year less 2-year Treasury yield), monthly averages in
  published percentage-point units.
- `phase1_wrds_pull_summary.csv`, `phase1_public_pull_summary.csv`,
  `ibes_link_rate_by_year.csv`, `ibes_industry_coverage.csv`,
  `signal_coverage_by_month.csv`, `signal_summary.csv`, and
  `sensitivity_2026_coverage.csv` are diagnostic outputs, not model feature
  panels. The MOM–REV correlation plot is saved to
  `results/figures/mom_rev_correlation.png`.

## 6. Data Quality Findings and Safe Inference

- **Coverage gap:** the CRSP pull ends in December 2025 while I/B/E/S summaries
  reach August 2026. The link file produces no linked 2026 firm-months. The
  2026 signal rows therefore have missing `rev` and `rev_alt`; do not read them
  as zero or use them to evaluate those revision signals, and never fill them
  with sensitivity values.
- **Separate sensitivity:** exact 2026 I/B/E/S CUSIPs are matched to a unique
  PERMNO in the latest CRSP names snapshot. ACTPSUM prices/shares are used only
  for the sensitivity; December 2025 SIC is carried for those 2026 rows. The
  sensitivity has 373 REV and 309 REV_ALT industry-months available. It is not
  the primary signal and does not validate extending annual `ibcrsphist` links.
- **Phase 2 link rate:** the link rate is 87.7% in 2025 and 0% in 2026. The
  coverage table explicitly includes all 49 industries for every I/B/E/S
  snapshot month and flags industry-months with fewer than five linked firms;
  all 392 2026 cells are flagged with zero firms.
- **No following-month return yet:** Ken French industry returns end in August
  2026, so August signal rows do not have September `next_return` values.
- **Carried characteristics:** no rows are carried in the current rebuilt
  output. Carry is limited to months after the dataset-wide CRSP end date;
  within covered CRSP history, a security-specific missing month is excluded.
  For future post-end carry rows, compare results with and without them.
- **I/B/E/S counts:** the pull contains records where `numup + numdown >
  numest`. WRDS labels these fields “Number Up” and “Number Down” but does not
  establish that they are mutually exclusive parts of `numest`; do not filter
  them solely on that inequality or call the remainder unchanged.
- **Extreme EPS estimates:** raw I/B/E/S consensus values include extremely
  large magnitudes, including some rows with at least 3 estimates. The main REV
  formula does not use `meanest`; the alternative change is winsorized at the
  firm-month level. Raw values are retained for audit, and sensitivity to
  unusual estimates is appropriate before drawing conclusions.
- **Financial tails:** stock prices and returns, industry returns, and future
  returns are not globally winsorized. Large values can be genuine market
  events or security-specific conventions. Investigate flagged observations;
  do not clip raw source data just because it is extreme. Standardized signal
  scores are already clipped at ±3.
- **Missing public history:** some industry return series have missing values
  before those industries have sufficient history. Momentum remains missing
  until its full 11-month lookback is available. FRED `BAA10Y` is missing where
  the source series has no observation; the October 2026 month is incomplete.
- **Count filters:** REV requires at least 3 estimates per firm and 5 firms per
  industry-month. REV_ALT additionally requires at least 3 estimates in both
  the current and lagged snapshots and a current, nonzero price.
- **Open team decision:** whether a link with `edate` equal to the link table's
  last observation date may be treated as continuing past that date. No such
  extension is applied pending team approval; 2026 REV should remain missing.

The data-pull and cleaning summaries are saved under `results/tables/`. The
current regression tests include end-to-end date alignment, the momentum window,
industry coverage and aggregation, missing-value preservation, the lagged
analyst-coverage rule, and CUSIP/ACTPSUM sensitivity eligibility.

## 7. Phase 4: IC and Blend

Run `python -m src.ic` after rebuilding `signals.parquet`. It evaluates each
month-t z-score against the corresponding `next_return` (industry return at
t+1), reporting both Spearman rank IC and Pearson correlation. The summary
table includes valid IC months, industry-month pairs, and coverage counts for
the full sample, post-2010, and the fixed most-recent-18-month window.

REV-orthogonal is calculated each month by an OLS regression of `rev_z` on
`mom_z` across industries where both are observed; the residual is then tested
against next-month returns. It is a diagnostic test, not a replacement for
REV.

Blend weights follow `w proportional to R inverse times mean IC`. At signal
month t, both the expanding mean-Spearman-IC vector and the MOM/REV correlation
matrix use only history from signal months strictly before t. That history's
next-month returns are observable by t, and at least 60 joint MOM/REV IC months
are required. Weights are normalized to sum to one. `blend_z` remains missing
unless both MOM and REV are available; it is not filled from the separate 2026
sensitivity.

Outputs are `ic_by_month.csv`, `ic_summary_by_horizon.csv`,
`blend_weights_by_month.csv`, and `signals_phase4.parquet` under the documented
results/data directories. Figures are `rolling_ic_mom_rev.png` and
`blend_weights.png` under `results/figures/`. With current data, the recent
March 2025–August 2026 window has 17 evaluable MOM months and 10 evaluable REV,
REV_ALT, REV-orthogonal, and blend months. Treat those shorter revision samples
as low-power descriptive evidence, not complete 18-month estimates.