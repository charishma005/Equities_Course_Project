# Industry Analyst Revisions vs. Industry Momentum

MFE 230G Active Asset Management, final project. Long-short strategy across the
49 Fama-French industries that blends industry price momentum with I/B/E/S
analyst EPS revisions. The full working plan, thesis, and rejection criterion
are in [`CLAUDE.md`](CLAUDE.md).

## Setup

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
| 2–9 | not yet implemented | |

Tests: `python -m pytest -q tests`

Pull scripts skip files that already exist; pass `--force` to re-pull.

## Conventions

- Monthly dates are **month-end timestamps** (last calendar day, `datetime64`),
  set by `src/utils.to_month_end` at load time.
- Returns are decimals; Ken French percent returns are divided by 100 on load,
  and `-99.99` / `-999` become NaN.
- All parameters are in `config.py`.
- `data/raw/` and `data/interim/` are git-ignored (licensed WRDS data).

## Status notes

### Phase 1: data pulls (code written, not yet run)

- Done: `src/pull_wrds.py` (I/B/E/S statsum, I/B/E/S-CRSP link with score <= 2,
  CRSP msf/msenames/msedelist) and `src/pull_public.py` (49 and 30 industry VW
  returns, Siccodes49/30, FF5, UMD, ST reversal, FRED BAA10Y/T10Y2Y). Offline
  parser tests pass.
- Not done: the pulls have not been run yet. They must run on a machine with
  WRDS access. Then fill in the table below from
  `results/tables/phase1_*_pull_summary.csv`.
- Watch for: legacy `crsp.msf` (SIZ format) may stop before the latest
  I/B/E/S month. `pull_wrds.py` prints the gap. Record it here (CLAUDE.md 4.4).

| File | Rows | First date | Last date |
|---|---|---|---|
| ibes_statsum | TBD | TBD | TBD |
| ibes_crsp_link | TBD | TBD | TBD |
| crsp_msf | TBD | TBD | TBD |
| crsp_msenames | TBD | | |
| crsp_msedelist | TBD | TBD | TBD |
| kf_ind49_vw | TBD | TBD | TBD |
| kf_ff5 / kf_umd / kf_strev | TBD | TBD | TBD |

CRSP coverage gap: TBD
