"""Clean CRSP and link I/B/E/S snapshots to historical stock characteristics.

All stock and I/B/E/S observations are assigned to calendar month-end. A
month-t signal uses the latest I/B/E/S snapshot published by that month-end
and CRSP characteristics valid at or before that month-end.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src.utils import save_parquet, to_month_end  # noqa: E402


def _numeric_id(values: pd.Series) -> pd.Series:
    """Normalize CRSP/link identifiers for consistent joins."""
    return pd.to_numeric(values, errors="coerce").astype("Int64")


def _map_industries(sic: pd.Series, ranges: pd.DataFrame,
                    other_industry: int) -> pd.Series:
    """Map SIC values to Ken French industry IDs, assigning unmatched SIC to Other."""
    mapped = pd.Series(pd.NA, index=sic.index, dtype="Int64")
    for row in ranges.itertuples(index=False):
        match = sic.between(int(row.sic_lo), int(row.sic_hi), inclusive="both")
        mapped.loc[match] = int(row.industry)
    return mapped.fillna(other_industry).astype("int64")


def prepare_crsp(msf: pd.DataFrame, names: pd.DataFrame,
                 sic_ranges: pd.DataFrame, delist: pd.DataFrame | None = None,
                 returns_include_delist: bool = False,
                 other_industry: int = 49) -> pd.DataFrame:
    """Build one historical CRSP stock-month panel.

    Inputs are the project's raw CRSP MSF, MSENAMES, MSEDELIST, and SIC-range
    tables. Output has month-end date, permno, total return, market cap in
    thousands of dollars, historical SIC, and industry ID.
    """
    stock = msf.copy()
    stock["permno"] = _numeric_id(stock["permno"])
    stock["date"] = to_month_end(stock["date"])
    stock["ret"] = pd.to_numeric(stock["ret"], errors="coerce")
    stock["prc"] = pd.to_numeric(stock["prc"], errors="coerce")
    stock["shrout"] = pd.to_numeric(stock["shrout"], errors="coerce")
    stock = stock.dropna(subset=["permno", "date"])

    name_rows = names.copy()
    name_rows["permno"] = _numeric_id(name_rows["permno"])
    for col in ("namedt", "nameendt"):
        name_rows[col] = pd.to_datetime(name_rows[col], errors="coerce")
    if "shrcd" in name_rows:
        name_rows["shrcd"] = pd.to_numeric(name_rows["shrcd"], errors="coerce")
    name_rows["exchcd"] = pd.to_numeric(name_rows["exchcd"], errors="coerce")
    name_rows["siccd"] = pd.to_numeric(name_rows["siccd"], errors="coerce")
    if "common_stock" in name_rows:
        name_rows["common_stock"] = name_rows["common_stock"].fillna(False).astype(bool)
    name_rows = name_rows.dropna(subset=["permno", "namedt"])
    name_rows = name_rows.sort_values(["namedt", "permno"])

    stock = pd.merge_asof(
        stock.sort_values(["date", "permno"]),
        name_rows.sort_values(["namedt", "permno"]),
        by="permno", left_on="date", right_on="namedt", direction="backward",
        allow_exact_matches=True,
    )
    name_valid = stock["nameendt"].isna() | (stock["date"] <= stock["nameendt"])
    common_stock = (stock["common_stock"].fillna(False) if "common_stock" in stock
                    else stock["shrcd"].isin(config.SHRCD_KEEP))
    keep = name_valid & common_stock & stock["exchcd"].isin(config.EXCHCD_KEEP)
    stock = stock.loc[keep].copy()

    delist_rows = pd.DataFrame() if delist is None else delist.copy()
    if returns_include_delist:
        stock["dlret"] = np.nan
    elif not delist_rows.empty:
        delist_rows["permno"] = _numeric_id(delist_rows["permno"])
        delist_rows["date"] = to_month_end(delist_rows["dlstdt"])
        delist_rows["dlret"] = pd.to_numeric(delist_rows["dlret"], errors="coerce")
        delist_rows = (delist_rows.dropna(subset=["permno", "date"])
                       .sort_values(["date", "permno"])
                       .drop_duplicates(["permno", "date"], keep="last"))
        stock = stock.merge(delist_rows[["permno", "date", "dlret"]],
                            on=["permno", "date"], how="left", validate="one_to_one")
    else:
        stock["dlret"] = np.nan
    both_returns = stock["ret"].notna() & stock["dlret"].notna()
    stock.loc[both_returns, "ret"] = (
        (1 + stock.loc[both_returns, "ret"]) *
        (1 + stock.loc[both_returns, "dlret"]) - 1
    )
    stock["ret"] = stock["ret"].where(stock["ret"].notna(), stock["dlret"])
    stock["mktcap"] = stock["prc"].abs() * stock["shrout"]
    stock["industry"] = _map_industries(stock["siccd"], sic_ranges, other_industry)
    stock["crsp_carried"] = False
    return (stock.sort_values(["date", "permno"])
            .drop_duplicates(["permno", "date"], keep="last")
            [["permno", "date", "ret", "prc", "mktcap", "siccd", "industry", "crsp_carried"]]
            .reset_index(drop=True))


def link_ibes(ibes: pd.DataFrame, links: pd.DataFrame,
              stock_monthly: pd.DataFrame,
              max_carry_months: int = config.CRSP_GAP_MAX_CARRY_MONTHS
              ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Link monthly I/B/E/S snapshots to CRSP using only contemporaneous history.

    Returns (firm-month panel, annual link-rate table). Links must be valid on
    the actual statpers date. CRSP characteristics must come from the same
    month, except for months after the last CRSP date, where they are carried
    forward at most max_carry_months (price is blanked when carried).
    """
    estimates = ibes.copy()
    estimates["ticker"] = estimates["ticker"].astype("string").str.strip()
    estimates["statpers"] = pd.to_datetime(estimates["statpers"], errors="coerce")
    estimates = estimates.dropna(subset=["ticker", "statpers"])
    estimates["month"] = to_month_end(estimates["statpers"])
    estimates = (estimates.sort_values(["statpers", "ticker"])
                 .drop_duplicates(["ticker", "month"], keep="last"))

    link_rows = links.copy()
    link_rows["ticker"] = link_rows["ticker"].astype("string").str.strip()
    link_rows["permno"] = _numeric_id(link_rows["permno"])
    link_rows["sdate"] = pd.to_datetime(link_rows["sdate"], errors="coerce")
    link_rows["edate"] = pd.to_datetime(link_rows["edate"], errors="coerce")
    link_rows["score"] = pd.to_numeric(link_rows["score"], errors="coerce")
    link_rows = link_rows.dropna(subset=["ticker", "permno", "sdate", "score"])
    link_rows = link_rows.loc[link_rows["score"] <= config.LINK_MAX_SCORE]
    candidates = estimates.merge(link_rows, on="ticker", how="left")
    valid = (candidates["permno"].notna() & (candidates["sdate"] <= candidates["statpers"])
             & (candidates["edate"].isna() | (candidates["statpers"] <= candidates["edate"])))
    candidates = candidates.loc[valid].copy()
    candidates = (candidates.sort_values(["ticker", "month", "score", "sdate", "permno"],
                                         ascending=[True, True, True, False, True])
                  .drop_duplicates(["ticker", "month"], keep="first"))
    linked_tickers = candidates[["ticker", "month"]].drop_duplicates()
    rate_source = estimates[["ticker", "month"]].drop_duplicates().merge(
        linked_tickers.assign(linked=True), on=["ticker", "month"], how="left")
    rate_source["year"] = rate_source["month"].dt.year
    rates = (rate_source.groupby("year", as_index=False)
             .agg(ibes_ticker_months=("ticker", "size"),
                  linked_ticker_months=("linked", "count")))
    rates["link_rate"] = rates["linked_ticker_months"] / rates["ibes_ticker_months"]

    chars = stock_monthly.copy()
    chars["permno"] = _numeric_id(chars["permno"])
    chars["date"] = to_month_end(chars["date"])
    crsp_end = chars["date"].max()
    chars = chars.sort_values(["date", "permno"])
    candidates["permno"] = _numeric_id(candidates["permno"])
    candidates = pd.merge_asof(
        candidates.sort_values(["month", "permno"]),
        chars.sort_values(["date", "permno"]),
        by="permno", left_on="month", right_on="date", direction="backward",
        allow_exact_matches=True,
    )
    has_crsp = candidates["date"].notna()
    month_gap = pd.Series(pd.NA, index=candidates.index, dtype="Int64")
    month_gap.loc[has_crsp] = (
        candidates.loc[has_crsp, "month"].dt.to_period("M").astype("int64") -
        candidates.loc[has_crsp, "date"].dt.to_period("M").astype("int64")
    )
    after_crsp_end = candidates["month"].gt(crsp_end)
    candidates["crsp_carried"] = after_crsp_end & month_gap.gt(0).fillna(False)
    exact_month = month_gap.eq(0).fillna(False)
    within_carry_limit = month_gap.le(max_carry_months).fillna(False)
    keep = exact_month | (candidates["crsp_carried"] & within_carry_limit)
    candidates = candidates.loc[keep].copy()
    candidates["crsp_date"] = candidates["date"]
    candidates["price_age_months"] = month_gap.loc[candidates.index].astype("Int64")
    candidates.loc[candidates["crsp_carried"], "prc"] = np.nan
    candidates["month"] = to_month_end(candidates["month"])
    candidates = (candidates.sort_values(["month", "permno", "statpers", "ticker"])
                  .drop_duplicates(["permno", "month"], keep="last"))
    output_cols = ["permno", "month", "statpers", "ticker", "fpedats", "numest",
                   "numup", "numdown", "meanest", "prc", "mktcap", "industry",
                   "crsp_date", "price_age_months", "crsp_carried", "score"]
    return candidates[output_cols].reset_index(drop=True), rates


def industry_coverage(ibes_panel: pd.DataFrame, estimate_months: pd.Series,
                      min_firms: int = config.MIN_FIRMS_PER_INDUSTRY) -> pd.DataFrame:
    """Count linked firms for every estimate month and 49-industry combination.

    Industries with no linked firms are retained with zero coverage and flagged.
    """
    months = (to_month_end(pd.Series(estimate_months)).dropna()
              .drop_duplicates().sort_values())
    grid = pd.MultiIndex.from_product(
        [months.tolist(), range(1, config.OTHER_INDUSTRY_49 + 1)],
        names=["month", "industry"],
    ).to_frame(index=False)
    panel = ibes_panel.copy()
    if not panel.empty:
        panel["month"] = to_month_end(panel["month"])
    if panel.empty:
        counts = pd.DataFrame(columns=["month", "industry", "firms"])
    else:
        counts = (panel.groupby(["month", "industry"], as_index=False)
                  .agg(firms=("permno", "nunique")))
    coverage = grid.merge(counts, on=["month", "industry"], how="left")
    coverage["firms"] = coverage["firms"].fillna(0).astype("int64")
    coverage["low_coverage"] = coverage["firms"] < min_firms
    return coverage


def main() -> None:
    """Run Phase 2 from raw parquet inputs and save interim coverage tables."""
    raw = config.DATA_RAW
    required = ["crsp_msf", "crsp_msenames", "ibes_crsp_link",
                "ibes_statsum", "kf_sic49"]
    missing = [raw / f"{name}.parquet" for name in required
               if not (raw / f"{name}.parquet").exists()]
    if missing:
        raise FileNotFoundError("Missing raw inputs: " + ", ".join(str(p) for p in missing))
    read = lambda name: pd.read_parquet(raw / f"{name}.parquet")
    ibes_source = read("ibes_statsum")
    stocks = prepare_crsp(read("crsp_msf"), read("crsp_msenames"),
                          read("kf_sic49"), returns_include_delist=True)
    ibes_panel, link_rates = link_ibes(ibes_source, read("ibes_crsp_link"), stocks)
    save_parquet(stocks, config.DATA_INTERIM / "crsp_monthly.parquet")
    save_parquet(ibes_panel, config.DATA_INTERIM / "ibes_crsp_monthly.parquet")
    config.TABLES.mkdir(parents=True, exist_ok=True)
    link_rates.to_csv(config.TABLES / "ibes_link_rate_by_year.csv", index=False)
    estimate_months = to_month_end(pd.to_datetime(ibes_source["statpers"], errors="coerce"))
    coverage = industry_coverage(ibes_panel, estimate_months)
    coverage.to_csv(config.TABLES / "ibes_industry_coverage.csv", index=False)
    print(link_rates.to_string(index=False))
    print(f"CRSP rows: {len(stocks):,}; linked I/B/E/S firm-months: {len(ibes_panel):,}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args()
    main()