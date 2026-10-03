"""Shared helpers: date normalization and parquet I/O."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def to_month_end(dates) -> pd.Series | pd.DatetimeIndex:
    """Normalize dates to the last calendar day of their month.

    Input: anything pd.to_datetime accepts (Series, Index, array, or a
    YYYYMM integer/string series). Output: same container type with
    datetime64 values at month end (00:00). This is the project's single
    monthly date convention.
    """
    s = dates
    if isinstance(s, (pd.Series, pd.Index)) and not pd.api.types.is_datetime64_any_dtype(s):
        as_str = s.astype(str).str.strip()
        if len(as_str) and as_str.str.fullmatch(r"\d{6}").all():
            s = pd.to_datetime(as_str, format="%Y%m")
    out = pd.to_datetime(s) + pd.offsets.MonthEnd(0)
    if isinstance(out, pd.Series):
        return out.dt.normalize()
    return out.normalize()


def save_parquet(df: pd.DataFrame, path: Path) -> None:
    """Write a compressed parquet file, creating parent dirs; print a summary."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, compression="zstd", index=False)
    print(f"saved {path.name}: {len(df):,} rows, {df.shape[1]} cols")
