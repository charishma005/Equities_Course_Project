"""Phase 1: pull I/B/E/S, the I/B/E/S-CRSP link table, and CRSP from WRDS.

Credentials are never stored in code. The `wrds` package reads ~/.pgpass
(created on first interactive login) or prompts at runtime. Set the
WRDS_USERNAME environment variable to skip the username prompt.

Outputs (all in data/raw/, never committed):
    ibes_statsum.parquet, ibes_crsp_link.parquet,
    crsp_msf.parquet, crsp_msenames.parquet

Timing: raw dates are saved as-is (statpers, CRSP date). Conversion to
month-end and the "latest statpers <= month end" rule happen in clean.py.

Usage:
    python -m src.pull_wrds            # skip files that already exist
    python -m src.pull_wrds --force    # re-pull everything
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src.utils import save_parquet  # noqa: E402

QUERIES = {
    "ibes_statsum": f"""
        SELECT ticker, cusip, statpers, fpedats, numest, numup, numdown,
               meanest, medest, stdev
        FROM ibes.statsum_epsus
        WHERE measure = 'EPS' AND fiscalp = 'ANN' AND fpi = '1'
          AND usfirm = 1 AND statpers >= '{config.IBES_START}'
    """,
    "ibes_crsp_link": f"""
        SELECT ticker, permno, sdate, edate, score
        FROM wrdsapps.ibcrsphist
        WHERE score <= {config.LINK_MAX_SCORE}
    """,
    "crsp_msf": f"""
                SELECT permno, mthcaldt AS date, mthret AS ret,
                             mthprc AS prc, shrout
                FROM crsp.msf_v2
                WHERE mthcaldt >= '{config.CRSP_START}'
                    AND securitytype = 'EQTY' AND securitysubtype = 'COM'
                    AND sharetype = 'NS' AND primaryexch IN ('N', 'A', 'Q')
    """,
    "crsp_msenames": """
                SELECT permno, namedt, nameenddt AS nameendt, siccd,
                             TRUE AS common_stock,
                             CASE primaryexch WHEN 'N' THEN 1 WHEN 'A' THEN 2
                                                                WHEN 'Q' THEN 3 END AS exchcd
                FROM crsp.stocknames_v2
                WHERE securitytype = 'EQTY' AND securitysubtype = 'COM'
                    AND sharetype = 'NS' AND primaryexch IN ('N', 'A', 'Q')
    """,
}

DATE_COLS = {
    "ibes_statsum": ["statpers", "fpedats"],
    "ibes_crsp_link": ["sdate", "edate"],
    "crsp_msf": ["date"],
    "crsp_msenames": ["namedt", "nameendt"],
    "crsp_msedelist": ["dlstdt"],
}


def connect():
    """Open a WRDS connection using ~/.pgpass or an interactive prompt.

    Output: wrds.Connection. No credentials are read from or written to the repo.
    """
    import wrds

    return wrds.Connection(wrds_username=os.environ.get("WRDS_USERNAME"))


def pull_one(db, name: str, force: bool = False) -> pd.DataFrame | None:
    """Run QUERIES[name], parse date columns, save to data/raw/{name}.parquet.

    Inputs: open WRDS connection, query name, force flag (re-pull if file exists).
    Output: the pulled DataFrame, or None if skipped because the file exists.
    """
    path = config.DATA_RAW / f"{name}.parquet"
    if path.exists() and not force:
        print(f"skip {name}: {path} exists (use --force to re-pull)")
        return None
    df = db.raw_sql(QUERIES[name], date_cols=DATE_COLS[name])
    save_parquet(df, path)
    return df


def summarize(name: str, df: pd.DataFrame) -> dict:
    """Return row count and date range for the primary date column of a pull."""
    col = DATE_COLS[name][0]
    return {
        "file": f"{name}.parquet",
        "rows": len(df),
        "date_col": col,
        "min_date": df[col].min(),
        "max_date": df[col].max(),
    }


def main(force: bool = False) -> None:
    """Pull every WRDS table, then print and save a row-count/date-range table.

    Also checks the CRSP vs. I/B/E/S end date (CLAUDE.md 3.3 / 4.4) and
    prints the gap so it can be recorded in README.md.
    """
    db = connect()
    try:
        for name in QUERIES:
            pull_one(db, name, force=force)
    finally:
        db.close()

    rows = [summarize(n, pd.read_parquet(config.DATA_RAW / f"{n}.parquet"))
            for n in QUERIES]
    summary = pd.DataFrame(rows)
    config.TABLES.mkdir(parents=True, exist_ok=True)
    summary.to_csv(config.TABLES / "phase1_wrds_pull_summary.csv", index=False)
    print(summary.to_string(index=False))

    crsp_end = summary.set_index("file").loc["crsp_msf.parquet", "max_date"]
    ibes_end = summary.set_index("file").loc["ibes_statsum.parquet", "max_date"]
    print(f"\nCRSP msf max date:      {crsp_end:%Y-%m-%d}")
    print(f"I/B/E/S statpers max:   {ibes_end:%Y-%m-%d}")
    if crsp_end < ibes_end:
        months = (ibes_end.to_period("M") - crsp_end.to_period("M")).n
        print(f"WARNING: CRSP ends {months} month(s) before I/B/E/S. "
              "Record this gap in README.md (CLAUDE.md 4.4).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="re-pull existing files")
    main(force=parser.parse_args().force)
