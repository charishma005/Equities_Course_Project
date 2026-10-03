"""Phase 1: pull public data (Ken French Data Library, FRED).

Ken French CSVs report percent returns and use -99.99 / -999 for missing.
Both are converted here: returns are saved in decimals (0.01 = 1%) and
missing codes become NaN. Dates are month-end timestamps.

Outputs (data/raw/):
    kf_ind49_vw.parquet   wide: date + one column per industry (decimal)
    kf_ind30_vw.parquet   same, 30 industries (Phase 8 robustness)
    kf_sic49.parquet      industry, short, name, sic_lo, sic_hi
    kf_sic30.parquet
    kf_ff5.parquet        date, Mkt-RF, SMB, HML, RMW, CMA, RF (decimal)
    kf_umd.parquet        date, UMD
    kf_strev.parquet      date, ST_Rev
    fred_macro.parquet    date, BAA10Y, T10Y2Y (monthly averages, NOT lagged;
                          the one-month lag is applied where used)

Usage:
    python -m src.pull_public [--force] [--no-fred]
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src.utils import save_parquet, to_month_end  # noqa: E402

_MONTH_ROW = re.compile(r"^\s*(\d{6})\s*,")
_SIC_INDUSTRY = re.compile(r"^\s*(\d{1,2})\s+(\S+)\s+(.+?)\s*$")
_SIC_RANGE = re.compile(r"^\s*(\d{4})-(\d{4})")


# --------------------------------------------------------------------------
# Download
# --------------------------------------------------------------------------
def download_zip_text(filename: str) -> str:
    """Download a Ken French zip and return the text of its single member file."""
    resp = requests.get(config.KF_BASE_URL + filename, timeout=60)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        member = zf.namelist()[0]
        return zf.read(member).decode("latin-1")


# --------------------------------------------------------------------------
# Parsers (pure functions, unit-tested offline)
# --------------------------------------------------------------------------
def parse_kf_monthly_tables(text: str) -> list[tuple[str, pd.DataFrame]]:
    """Split a Ken French CSV into its monthly tables.

    Input: raw file text. A table is a header line starting with ',' followed
    by rows whose first field is a 6-digit YYYYMM date. Annual tables
    (4-digit years) are ignored. The title is the last non-blank, non-data
    line before the header ('' if none).

    Output: list of (title, DataFrame) in file order. DataFrames have a
    month-end 'date' column and float columns in DECIMALS, with Ken French
    missing codes set to NaN.
    """
    tables: list[tuple[str, pd.DataFrame]] = []
    title, header, rows = "", None, []

    def flush():
        if header is not None and rows:
            df = pd.DataFrame(rows, columns=["date"] + header)
            df["date"] = to_month_end(df["date"])
            vals = df[header].apply(pd.to_numeric, errors="coerce")
            vals = vals.mask(vals.isin(config.KF_MISSING) | (vals <= -99.99))
            df[header] = vals / 100.0
            tables.append((title, df))

    for line in text.splitlines():
        if _MONTH_ROW.match(line) and header is not None:
            fields = [f.strip() for f in line.split(",")]
            rows.append(fields[: len(header) + 1])
        elif line.strip().startswith(","):
            flush()
            header = [h.strip() for h in line.split(",")[1:]]
            rows = []
        else:
            if header is not None and rows:
                flush()
                header, rows = None, []
            elif header is not None and not rows and line.strip():
                header = None  # header followed by non-monthly rows (annual)
            if line.strip() and not line.strip()[0].isdigit():
                title = line.strip()
    flush()
    return tables


def select_table(tables, title_contains: str | None = None) -> pd.DataFrame:
    """Return the first monthly table whose title contains `title_contains`
    (case-insensitive), or the first table if None. Raises if none match."""
    for title, df in tables:
        if title_contains is None or title_contains.lower() in title.lower():
            return df
    raise ValueError(f"no monthly table with title containing {title_contains!r}")


def parse_siccodes(text: str) -> pd.DataFrame:
    """Parse a Ken French SicodesNN.txt file into SIC ranges.

    Input: file text, industry header lines like ' 1 Agric  Agriculture'
    followed by range lines like '   0100-0199 Agricultural production'.
    Output: DataFrame(industry:int, short:str, name:str, sic_lo:int, sic_hi:int),
    one row per range. Industries listed with no ranges (e.g. 'Other') get
    no rows; the caller maps unmatched SIC codes to Other (CLAUDE.md 4.2).
    """
    out, current = [], None
    for line in text.splitlines():
        m_rng = _SIC_RANGE.match(line)
        if m_rng and current is not None:
            out.append((*current, int(m_rng.group(1)), int(m_rng.group(2))))
            continue
        m_ind = _SIC_INDUSTRY.match(line)
        if m_ind:
            current = (int(m_ind.group(1)), m_ind.group(2), m_ind.group(3))
    return pd.DataFrame(out, columns=["industry", "short", "name", "sic_lo", "sic_hi"])


def fred_monthly_mean(csv_text: str, series: str) -> pd.DataFrame:
    """Convert a FRED daily CSV to monthly averages indexed by month end.

    Output: DataFrame(date, <series>) in percentage points as published
    (spreads, not returns). No lag applied here.
    """
    df = pd.read_csv(io.StringIO(csv_text))
    df.columns = ["date", series]
    df["date"] = pd.to_datetime(df["date"])
    df[series] = pd.to_numeric(df[series], errors="coerce")  # FRED uses '.'
    df["date"] = to_month_end(df["date"])
    return df.groupby("date", as_index=False)[series].mean()


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def _ken_french(force: bool) -> list[dict]:
    targets = {
        "kf_ind49_vw": ("ind49", "Value Weighted Returns -- Monthly"),
        "kf_ind30_vw": ("ind30", "Value Weighted Returns -- Monthly"),
        "kf_ff5": ("ff5", None),
        "kf_umd": ("umd", None),
        "kf_strev": ("strev", None),
    }
    summary = []
    for out_name, (key, title) in targets.items():
        path = config.DATA_RAW / f"{out_name}.parquet"
        if path.exists() and not force:
            df = pd.read_parquet(path)
        else:
            df = select_table(parse_kf_monthly_tables(
                download_zip_text(config.KF_FILES[key])), title)
            if out_name == "kf_umd":
                df = df.rename(columns={"Mom": "UMD"})
            save_parquet(df, path)
        summary.append({"file": path.name, "rows": len(df),
                        "min_date": df["date"].min(), "max_date": df["date"].max()})

    for out_name, key in {"kf_sic49": "sic49", "kf_sic30": "sic30"}.items():
        path = config.DATA_RAW / f"{out_name}.parquet"
        if path.exists() and not force:
            df = pd.read_parquet(path)
        else:
            df = parse_siccodes(download_zip_text(config.KF_FILES[key]))
            save_parquet(df, path)
        summary.append({"file": path.name, "rows": len(df),
                        "min_date": pd.NaT, "max_date": pd.NaT})
    return summary


def _fred(force: bool) -> list[dict]:
    path = config.DATA_RAW / "fred_macro.parquet"
    if path.exists() and not force:
        df = pd.read_parquet(path)
    else:
        df = None
        for s in config.FRED_SERIES:
            resp = requests.get(config.FRED_URL.format(series=s), timeout=60)
            resp.raise_for_status()
            m = fred_monthly_mean(resp.text, s)
            df = m if df is None else df.merge(m, on="date", how="outer")
        save_parquet(df, path)
    return [{"file": path.name, "rows": len(df),
             "min_date": df["date"].min(), "max_date": df["date"].max()}]


def main(force: bool = False, fred: bool = True) -> None:
    """Pull all public data and save a row-count/date-range summary table."""
    summary = _ken_french(force) + (_fred(force) if fred else [])
    out = pd.DataFrame(summary)
    config.TABLES.mkdir(parents=True, exist_ok=True)
    out.to_csv(config.TABLES / "phase1_public_pull_summary.csv", index=False)
    print(out.to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-fred", action="store_true", help="skip optional FRED pull")
    args = parser.parse_args()
    main(force=args.force, fred=not args.no_fred)
