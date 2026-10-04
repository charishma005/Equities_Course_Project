"""Pull I/B/E/S prices and a CRSP CUSIP reference for a 2026 sensitivity only."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src.pull_wrds import connect  # noqa: E402
from src.utils import save_parquet  # noqa: E402

QUERIES = {
    "ibes_actpsum_2026": f"""
        SELECT ticker, cusip, statpers, measure, usfirm, price, prdays, shout,
               curr_price
        FROM ibes.actpsum_epsus
        WHERE statpers >= '{config.IBES_SENSITIVITY_START}'
          AND measure = 'EPS' AND usfirm = 1
    """,
    "crsp_cusip_reference": """
        WITH crsp_end AS (
            SELECT max(mthcaldt)::date AS reference_date
            FROM crsp.msf_v2
        )
        SELECT n.permno, n.cusip, n.siccd, n.namedt,
               n.nameenddt AS nameendt, e.reference_date
        FROM crsp.stocknames_v2 AS n
        CROSS JOIN crsp_end AS e
        WHERE n.namedt <= e.reference_date
          AND (n.nameenddt IS NULL OR n.nameenddt >= e.reference_date)
          AND n.securitytype = 'EQTY' AND n.securitysubtype = 'COM'
          AND n.sharetype = 'NS' AND n.primaryexch IN ('N', 'A', 'Q')
          AND n.cusip IS NOT NULL
    """,
}

DATE_COLS = {
    "ibes_actpsum_2026": ["statpers", "prdays"],
    "crsp_cusip_reference": ["namedt", "nameendt", "reference_date"],
}


def main(force: bool = False) -> None:
    """Pull price/share sensitivity inputs without changing primary panels."""
    config.DATA_RAW.mkdir(parents=True, exist_ok=True)
    db = connect()
    try:
        for name, query in QUERIES.items():
            path = config.DATA_RAW / f"{name}.parquet"
            if path.exists() and not force:
                print(f"skip {name}: {path} exists (use --force to re-pull)")
                continue
            frame = db.raw_sql(query, date_cols=DATE_COLS[name])
            save_parquet(frame, path)
    finally:
        db.close()

    summary = []
    for name in QUERIES:
        path = config.DATA_RAW / f"{name}.parquet"
        frame = pd.read_parquet(path)
        date_col = DATE_COLS[name][0]
        summary.append({
            "file": path.name,
            "rows": len(frame),
            "date_col": date_col,
            "min_date": frame[date_col].min(),
            "max_date": frame[date_col].max(),
        })
    config.TABLES.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(summary).to_csv(
        config.TABLES / "phase_2026_sensitivity_pull_summary.csv", index=False)
    print(pd.DataFrame(summary).to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="re-pull existing files")
    main(force=parser.parse_args().force)