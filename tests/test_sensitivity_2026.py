"""Tests for the isolated, CUSIP-validated 2026 sensitivity panel."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.sensitivity_2026 import build_2026_sensitivity  # noqa: E402


def _sample_inputs():
    tickers = [f"TICK{i}" for i in range(5)]
    cusips = [f"C{i:07d}" for i in range(5)]
    estimates = []
    prices = []
    reference = []
    for index, (ticker, cusip) in enumerate(zip(tickers, cusips)):
        for snapshot, fpedats, meanest, numup, numdown in [
            ("2025-10-16", "2026-12-31", 0.5, 1, 0),
            ("2026-01-15", "2026-12-31", 1.0, 2, 1),
            ("2026-04-16", "2026-12-31", 2.0, 3, 1),
        ]:
            estimates.append({
                "ticker": ticker, "cusip": cusip, "statpers": snapshot,
                "fpedats": fpedats, "numest": 4,
                "numup": numup, "numdown": numdown, "meanest": meanest,
            })
            if snapshot >= "2026-01-01":
                prices.append({
                    "ticker": ticker, "cusip": cusip, "statpers": snapshot,
                    "measure": "EPS", "usfirm": 1, "price": 10.0,
                    "prdays": snapshot, "shout": 100.0, "curr_price": "USD",
                })
        reference.append({
            "permno": 100 + index, "cusip": cusip, "siccd": 100,
            "namedt": "2020-01-01", "nameendt": "2025-12-31",
            "reference_date": "2025-12-31",
        })
    sic_ranges = pd.DataFrame({
        "industry": [1], "sic_lo": [100], "sic_hi": [199], "short": ["Agric"],
    })
    return (pd.DataFrame(estimates), pd.DataFrame(prices),
            pd.DataFrame(reference), sic_ranges)


def test_builds_flagged_sensitivity_with_expected_revision_measures():
    estimates, prices, reference, sic_ranges = _sample_inputs()

    signals, coverage = build_2026_sensitivity(
        estimates, prices, reference, sic_ranges,
    )
    april = signals.loc[
        signals["month"].eq(pd.Timestamp("2026-04-30"))
        & signals["industry"].eq(1)
    ].iloc[0]
    january = signals.loc[
        signals["month"].eq(pd.Timestamp("2026-01-31"))
        & signals["industry"].eq(1)
    ].iloc[0]

    assert april["rev_sens"] == pytest.approx((3 - 1) / 4)
    assert april["rev_alt_sens"] == pytest.approx((2.0 - 1.0) / 10.0)
    assert april["rev_sens_firms"] == 5
    assert january["rev_alt_sens"] == pytest.approx((1.0 - 0.5) / 10.0)
    assert april["sensitivity_only"]
    assert april["link_method"] == "exact_cusip_unique_permno"
    assert coverage.loc[coverage["month"].eq(pd.Timestamp("2026-04-30")),
                        "eligible_firms"].iloc[0] == 5


def test_excludes_ambiguous_cusip_and_non_usd_price():
    estimates, prices, reference, sic_ranges = _sample_inputs()
    prices.loc[prices["ticker"].eq("TICK0") & prices["statpers"].eq("2026-04-16"),
               "curr_price"] = "EUR"
    ambiguous = reference.iloc[[1]].copy()
    ambiguous["permno"] = 999
    reference = pd.concat([reference, ambiguous], ignore_index=True)

    signals, coverage = build_2026_sensitivity(
        estimates, prices, reference, sic_ranges,
    )
    april = signals.loc[
        signals["month"].eq(pd.Timestamp("2026-04-30"))
        & signals["industry"].eq(1)
    ].iloc[0]
    april_coverage = coverage.loc[
        coverage["month"].eq(pd.Timestamp("2026-04-30"))
    ].iloc[0]

    assert april_coverage["eligible_firms"] == 3
    assert pd.isna(april["rev_sens"])
    assert pd.isna(april["rev_alt_sens"])