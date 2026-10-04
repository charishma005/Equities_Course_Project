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
| 2. Clean and link | `python -m src.clean` | `data/interim/*.parquet`, coverage tables |
| 3. Build signals | `python -m src.signals` | `data/processed/signals.parquet`, coverage tables, MOM–REV correlation figure |
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

### Phases 2–3: cleaning and signals (code updated 2026-10-04; rerun needed)

- Momentum now follows CLAUDE.md 5.1: months t-11 through t-1, skipping only
  month t. The earlier version used t-12 through t-2.
- CRSP market cap and SIC are carried forward only for months after CRSP ends
  (CLAUDE.md 4.4). The earlier version also carried them across mid-sample gaps
  (5,234 rows); those firm-months are now dropped.
- 2026: primary REV and REV_ALT are missing from January 2026 on and stay
  missing (CLAUDE.md 4.4). MOM runs through August 2026; its last evaluable
  month is July 2026. The recent window stays March 2025–August 2026, and
  `results/tables/signal_coverage_by_horizon.csv` reports how many months each
  signal covers in each window.
- New outputs: `ibes_industry_coverage.csv` now flags industry-months with fewer
  than 5 eligible firms; `signal_coverage_by_month.csv`,
  `signal_coverage_by_horizon.csv`, `mom_rev_xs_corr_by_month.csv`, and
  `results/figures/mom_rev_xs_corr.png`.
- Key numbers (link rates by year, carried rows, coverage): TBD after rerunning
  `python -m src.clean` and `python -m src.signals`.
