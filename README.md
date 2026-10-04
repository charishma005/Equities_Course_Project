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
| 1. ...or import web-query downloads | `python -m src.import_wrds_files ~/Downloads/<file> ...` | same files as above |
| 1. Data pulls (public) | `python -m src.pull_public` | `data/raw/kf_*.parquet`, `fred_macro.parquet` |
| Optional 2026 revision sensitivity | `python -m src.pull_2026_sensitivity && python -m src.sensitivity_2026` | separately flagged sensitivity parquet and coverage CSV |
| 2. Clean and link | `python -m src.clean` | `data/interim/*.parquet`, coverage tables |
| 3. Build signals | `python -m src.signals` | signals, monthly coverage, correlation figure |
| 4–8. IC, risk, portfolio, attribution, robustness | not yet implemented | |

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
