"""Build a separate 2026 I/B/E/S-price revision sensitivity panel."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from src.clean import _map_industries  # noqa: E402
from src.signals import _zscore, industry_revisions  # noqa: E402
from src.utils import to_month_end, save_parquet  # noqa: E402


def build_2026_sensitivity(
    ibes: pd.DataFrame,
    actpsum: pd.DataFrame,
    crsp_reference: pd.DataFrame,
    sic_ranges: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build a separately flagged revision panel and matching coverage audit.

    I/B/E/S EPS snapshots are joined to ACTPSUM on ticker and statpers. A firm
    is usable only when estimate and price CUSIPs agree, the reference CUSIP
    maps to exactly one CRSP PERMNO, and ACTPSUM has a positive USD price and
    positive shares with a pricing date no more than 31 days before statpers.
    Industry is the SIC-derived industry at the latest CRSP reference date.
    The outputs are sensitivity-only and do not replace primary signals.
    """
    estimates = ibes.copy()
    estimates["ticker"] = estimates["ticker"].astype("string").str.strip()
    estimates["cusip"] = estimates["cusip"].astype("string").str.strip().str.upper()
    estimates["statpers"] = pd.to_datetime(estimates["statpers"], errors="coerce")
    estimates["fpedats"] = pd.to_datetime(estimates["fpedats"], errors="coerce")
    estimates = estimates.dropna(subset=["ticker", "cusip", "statpers"])
    sensitivity_start = pd.Timestamp(config.IBES_SENSITIVITY_START)
    lag_start = sensitivity_start - pd.DateOffset(months=config.REV_ALT_LAG_MONTHS)
    estimates = estimates.loc[
        estimates["statpers"].ge(lag_start)
    ].copy()
    estimates["month"] = to_month_end(estimates["statpers"])
    estimates = (estimates.sort_values(["statpers", "ticker"])
                 .drop_duplicates(["ticker", "month"], keep="last"))
    for col in ("numest", "numup", "numdown", "meanest"):
        estimates[col] = pd.to_numeric(estimates[col], errors="coerce")

    prices = actpsum.copy()
    prices["ticker"] = prices["ticker"].astype("string").str.strip()
    prices["cusip"] = prices["cusip"].astype("string").str.strip().str.upper()
    prices["statpers"] = pd.to_datetime(prices["statpers"], errors="coerce")
    prices["prdays"] = pd.to_datetime(prices["prdays"], errors="coerce")
    prices["measure"] = prices["measure"].astype("string").str.strip().str.upper()
    prices["curr_price"] = prices["curr_price"].astype("string").str.strip().str.upper()
    prices["usfirm"] = pd.to_numeric(prices["usfirm"], errors="coerce")
    for col in ("price", "shout"):
        prices[col] = pd.to_numeric(prices[col], errors="coerce")
    prices = prices.loc[
        prices["measure"].eq("EPS") & prices["usfirm"].eq(1)
        & prices["statpers"].ge(pd.Timestamp(config.IBES_SENSITIVITY_START))
    ].copy()
    if prices.duplicated(["ticker", "statpers"]).any():
        raise ValueError("ACTPSUM has duplicate (ticker, statpers) rows")
    prices = prices.rename(columns={"cusip": "actpsum_cusip"})

    reference = crsp_reference.copy()
    reference["cusip"] = reference["cusip"].astype("string").str.strip().str.upper()
    reference["permno"] = pd.to_numeric(reference["permno"], errors="coerce")
    reference["siccd"] = pd.to_numeric(reference["siccd"], errors="coerce")
    reference["reference_date"] = pd.to_datetime(reference["reference_date"], errors="coerce")
    reference = reference.dropna(subset=["cusip", "permno", "reference_date"])
    reference_dates = reference["reference_date"].drop_duplicates()
    if len(reference_dates) != 1:
        raise ValueError("CRSP CUSIP reference must have exactly one reference date")
    reference_date = reference_dates.iloc[0]
    by_cusip = (reference.groupby("cusip", as_index=False)
                .agg(permno_count=("permno", "nunique"),
                     permno=("permno", "min"), siccd=("siccd", "min")))

    frame = estimates.merge(
        prices[["ticker", "statpers", "actpsum_cusip", "price", "shout",
                "prdays", "curr_price"]],
        on=["ticker", "statpers"], how="left", validate="one_to_one",
        indicator="actpsum_join",
    )
    frame = frame.merge(by_cusip, on="cusip", how="left", validate="many_to_one")
    frame["actpsum_match"] = frame["actpsum_join"].eq("both")
    frame["is_sensitivity_month"] = frame["statpers"].ge(sensitivity_start)
    frame["cusip_match"] = frame["cusip"].eq(frame["actpsum_cusip"])
    frame["permno_count"] = frame["permno_count"].fillna(0).astype("int64")
    frame["price_age_days"] = (frame["statpers"] - frame["prdays"]).dt.days
    frame["valid_price"] = (
        frame["curr_price"].eq("USD") & frame["price"].gt(0)
        & frame["shout"].gt(0) & frame["price_age_days"].between(
            0, config.SENSITIVITY_MAX_PRICE_AGE_DAYS)
    )
    frame["sensitivity_eligible"] = (
        frame["is_sensitivity_month"] & frame["actpsum_match"]
        & frame["cusip_match"] & frame["permno_count"].eq(1)
        & frame["valid_price"]
        & frame["siccd"].notna()
    )

    eligible = frame.loc[frame["sensitivity_eligible"]].copy()
    eligible["industry"] = _map_industries(
        eligible["siccd"], sic_ranges, config.OTHER_INDUSTRY_49)
    eligible["prc"] = eligible["price"]
    eligible["mktcap"] = eligible["price"] * eligible["shout"]
    eligible = (eligible.sort_values(["month", "permno", "statpers", "ticker"])
                .drop_duplicates(["permno", "month"], keep="last"))

    lag_only = frame.loc[
        ~frame["is_sensitivity_month"] & frame["permno_count"].eq(1)
        & frame["siccd"].notna()
    ].copy()
    lag_only["industry"] = _map_industries(
        lag_only["siccd"], sic_ranges, config.OTHER_INDUSTRY_49)
    lag_only["prc"] = np.nan
    lag_only["mktcap"] = np.nan
    firm_panel = pd.concat([eligible, lag_only], ignore_index=True)

    revisions = industry_revisions(firm_panel, config.MIN_ANALYSTS,
                                   config.MIN_FIRMS_PER_INDUSTRY)
    revisions = revisions.loc[revisions["month"].ge(sensitivity_start)]
    months = (estimates.loc[estimates["statpers"].ge(sensitivity_start), "month"]
              .drop_duplicates().sort_values().tolist())
    grid = pd.MultiIndex.from_product(
        [months, range(1, config.OTHER_INDUSTRY_49 + 1)],
        names=["month", "industry"],
    ).to_frame(index=False)
    signals = grid.merge(revisions, on=["month", "industry"], how="left")
    signals = signals.rename(columns={
        "rev": "rev_sens", "rev_firms": "rev_sens_firms",
        "rev_alt": "rev_alt_sens", "rev_alt_firms": "rev_alt_sens_firms",
    })
    for col in ("rev_sens_firms", "rev_alt_sens_firms"):
        signals[col] = signals[col].fillna(0).astype("int64")
    signals["rev_sens_z"] = signals.groupby("month")["rev_sens"].transform(
        lambda values: _zscore(values, config.Z_WINSOR))
    signals["rev_alt_sens_z"] = signals.groupby("month")["rev_alt_sens"].transform(
        lambda values: _zscore(values, config.Z_WINSOR))
    signals["sensitivity_only"] = True
    signals["link_method"] = "exact_cusip_unique_permno"
    signals["price_source"] = "ibes.actpsum_epsus"
    signals["market_cap_source"] = "ACTPSUM price * shares outstanding (millions)"
    signals["industry_source"] = "CRSP SIC at reference date, carried into 2026"
    signals["crsp_reference_date"] = reference_date

    current_frame = frame.loc[frame["is_sensitivity_month"]]
    coverage = (current_frame.groupby("month", as_index=False)
                .agg(ibes_ticker_snapshots=("ticker", "nunique"),
                     actpsum_matches=("actpsum_match", "sum"),
                     cusip_matches=("cusip_match", "sum"),
                     unique_permno_matches=("permno_count", lambda x: int(x.eq(1).sum())),
                     valid_usd_fresh_prices=("valid_price", "sum"),
                     eligible_firms=("sensitivity_eligible", "sum")))
    sensitivity_coverage = (signals.groupby("month", as_index=False)
                            .agg(rev_industries=("rev_sens", "count"),
                                 rev_alt_industries=("rev_alt_sens", "count")))
    coverage = coverage.merge(sensitivity_coverage, on="month", how="left")
    return signals, coverage


def main() -> None:
    """Build separate sensitivity outputs from pulled data; leave primary signals unchanged."""
    raw = config.DATA_RAW
    inputs = {
        "ibes_statsum": raw / "ibes_statsum.parquet",
        "ibes_actpsum_2026": raw / "ibes_actpsum_2026.parquet",
        "crsp_cusip_reference": raw / "crsp_cusip_reference.parquet",
        "kf_sic49": raw / "kf_sic49.parquet",
    }
    missing = [path for path in inputs.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing sensitivity inputs: " + ", ".join(map(str, missing)))
    signal, coverage = build_2026_sensitivity(
        pd.read_parquet(inputs["ibes_statsum"]),
        pd.read_parquet(inputs["ibes_actpsum_2026"]),
        pd.read_parquet(inputs["crsp_cusip_reference"]),
        pd.read_parquet(inputs["kf_sic49"]),
    )
    save_parquet(signal, config.DATA_PROCESSED / "signals_2026_sensitivity.parquet")
    config.TABLES.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(config.TABLES / "sensitivity_2026_coverage.csv", index=False)
    print(f"2026 sensitivity: {len(signal):,} industry-months; "
          f"REV available in {signal.groupby('month')['rev_sens'].count().sum():,} cells")
    print(coverage.to_string(index=False))


if __name__ == "__main__":
    main()