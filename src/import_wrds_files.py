"""Phase 1 (alternative): import WRDS web-query downloads into data/raw/.

Use this instead of pull_wrds.py when the data was downloaded through the
WRDS website (CSV, compressed CSV, Excel, SAS, Stata, or parquet). The
dataset is identified from its columns, column names are lowercased, date
columns are parsed, and the result is saved under the same filename
pull_wrds.py would produce, so later phases do not care how data arrived.

Web-query downloads do not include the filter columns (measure, fiscalp,
fpi, usfirm), so those filters must have been set in the WRDS form. This
script cannot verify them; it prints checks that catch the common mistakes.

Usage:
    python -m src.import_wrds_files ~/Downloads/ibes.csv [more files ...]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src.pull_wrds import DATE_COLS  # noqa: E402
from src.utils import save_parquet  # noqa: E402

# Columns that identify each dataset (CLAUDE.md 3.1-3.3)
REQUIRED = {
    "ibes_statsum": ["ticker", "cusip", "statpers", "fpedats", "numest",
                     "numup", "numdown", "meanest", "medest", "stdev"],
    "ibes_crsp_link": ["ticker", "permno", "sdate", "edate", "score"],
    "crsp_msf": ["permno", "date", "ret", "prc", "shrout"],
    "crsp_msenames": ["permno", "namedt", "nameendt", "siccd", "shrcd", "exchcd"],
    "crsp_msedelist": ["permno", "dlstdt", "dlret"],
}

# CRSP returns can contain letter codes (e.g. 'C', 'B') for missing values
NUMERIC_COERCE = {
    "crsp_msf": ["ret", "prc", "shrout"],
    "crsp_msedelist": ["dlret"],
    "ibes_statsum": ["numest", "numup", "numdown", "meanest", "medest", "stdev"],
}


def read_any(path: Path) -> pd.DataFrame:
    """Read a WRDS download by file extension. Output: raw DataFrame."""
    name = path.name.lower()
    if name.endswith((".csv", ".csv.gz", ".txt")):
        return pd.read_csv(path, low_memory=False)
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(path)
    if name.endswith(".sas7bdat"):
        return pd.read_sas(path, encoding="latin-1")
    if name.endswith(".dta"):
        return pd.read_stata(path)
    if name.endswith(".parquet"):
        return pd.read_parquet(path)
    raise ValueError(f"unsupported file type: {path.name}")


def identify(columns) -> str:
    """Return the dataset name whose required columns are all present.

    Checked most-specific first so e.g. msenames is not mistaken for msf.
    Raises ValueError listing what is missing if nothing matches.
    """
    cols = set(columns)
    for name in sorted(REQUIRED, key=lambda n: -len(REQUIRED[n])):
        if set(REQUIRED[name]) <= cols:
            return name
    raise ValueError(f"columns {sorted(cols)} do not match any expected WRDS dataset")


def parse_dates(s: pd.Series) -> pd.Series:
    """Parse WRDS dates given as datetimes, YYYY-MM-DD strings, or YYYYMMDD numbers.

    WRDS uses blanks/NaN for open-ended end dates; those stay NaT.
    """
    if pd.api.types.is_datetime64_any_dtype(s):
        return s
    as_str = s.astype("string").str.strip().str.replace(r"\.0$", "", regex=True)
    if as_str.dropna().str.fullmatch(r"\d{8}").all():
        return pd.to_datetime(as_str, format="%Y%m%d", errors="coerce")
    return pd.to_datetime(as_str, errors="coerce")


def apply_ibes_filters(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the CLAUDE.md 3.1 filters for any filter column the download kept.

    Input: lowercased I/B/E/S frame. Web-query downloads often include
    measure and fpi (sometimes fiscalp, usfirm); columns that are absent
    cannot be checked and are reported. Output: filtered frame.
    """
    wanted = {"measure": "EPS", "fpi": "1", "fiscalp": "ANN", "usfirm": "1"}
    for col, value in wanted.items():
        if col not in df:
            print(f"  NOTE: no '{col}' column; make sure {col}={value} was set in the WRDS form.")
            continue
        vals = df[col].astype("string").str.strip().str.replace(r"\.0$", "", regex=True)
        keep = vals.str.upper() == value
        counts = vals.value_counts(dropna=False).head(5).to_dict()
        print(f"  {col}: values {counts}; keeping {col}={value} "
              f"({keep.sum():,} of {len(df):,} rows)")
        df = df[keep.fillna(False)]
    return df


def normalize(df: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    """Lowercase columns, identify dataset, keep required columns, fix types.

    Output: (dataset name, cleaned DataFrame with the same columns pull_wrds.py
    would produce). Raises if any date column fails to parse entirely.
    """
    df = df.rename(columns=lambda c: str(c).strip().lower())
    name = identify(df.columns)
    if name == "ibes_statsum":
        df = apply_ibes_filters(df)
    df = df[REQUIRED[name]].copy()
    for col in DATE_COLS[name]:
        parsed = parse_dates(df[col])
        if df[col].notna().any() and parsed.isna().all():
            raise ValueError(f"{name}.{col}: could not parse any dates")
        df[col] = parsed
    for col in NUMERIC_COERCE.get(name, []):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "ticker" in df:
        df["ticker"] = df["ticker"].astype("string").str.strip()
    return name, df


def report(name: str, df: pd.DataFrame) -> None:
    """Print row count, date range, and sanity checks for one dataset."""
    col = DATE_COLS[name][0]
    print(f"  rows: {len(df):,}   {col}: {df[col].min():%Y-%m-%d} to {df[col].max():%Y-%m-%d}")
    if name == "ibes_statsum":
        dup = df.duplicated(["ticker", "statpers"]).sum()
        if dup:
            print(f"  WARNING: {dup:,} duplicate (ticker, statpers) rows. Several "
                  "forecast periods per snapshot usually means FPI=1 was not "
                  "set in the WRDS form (or quarterly periods were included).")
        if df["statpers"].min() > pd.Timestamp(config.IBES_START) + pd.DateOffset(months=1):
            print(f"  NOTE: data starts after {config.IBES_START} (plan start date).")
        bad = (df["numup"] + df["numdown"] > df["numest"]).sum()
        if bad:
            print(f"  NOTE: {bad:,} rows with numup + numdown > numest.")
    if name == "ibes_crsp_link" and (df["score"] > config.LINK_MAX_SCORE).any():
        print(f"  NOTE: link scores above {config.LINK_MAX_SCORE} present; "
              "clean.py will drop them.")


def main(paths: list[Path], force: bool = False) -> None:
    """Import each file to data/raw/<dataset>.parquet (refuses to overwrite
    unless force=True)."""
    for path in paths:
        print(f"{path}")
        try:
            name, df = normalize(read_any(path))
        except ValueError as err:
            print(f"  SKIPPED: {err}")
            continue
        out = config.DATA_RAW / f"{name}.parquet"
        if out.exists() and not force:
            print(f"  skip: {out} exists (use --force to overwrite)")
            continue
        print(f"  identified as: {name}")
        report(name, df)
        save_parquet(df, out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    main([p.expanduser() for p in args.files], force=args.force)
