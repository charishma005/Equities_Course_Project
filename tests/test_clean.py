"""Offline tests for historical CRSP cleaning and I/B/E/S timing."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.clean import industry_coverage, link_ibes, prepare_crsp  # noqa: E402


def test_prepare_crsp_uses_historical_name_and_combines_delisting_return():
    msf = pd.DataFrame({
        "permno": [1, 1], "date": ["1990-01-31", "1990-02-28"],
        "ret": [0.10, None], "prc": [-10.0, 11.0], "shrout": [100, 100],
    })
    names = pd.DataFrame({
        "permno": [1, 1], "namedt": ["1989-01-01", "1990-02-01"],
        "nameendt": ["1990-01-31", "1990-12-31"], "siccd": [100, 2000],
        "shrcd": [10, 11], "exchcd": [1, 3],
    })
    delist = pd.DataFrame({"permno": [1], "dlstdt": ["1990-02-15"], "dlret": [-0.30]})
    ranges = pd.DataFrame({"industry": [1], "sic_lo": [100], "sic_hi": [199]})

    out = prepare_crsp(msf, names, ranges, delist)

    assert out["industry"].tolist() == [1, 49]
    assert out["ret"].tolist() == pytest.approx([0.10, -0.30])
    assert out["mktcap"].tolist() == [1000, 1100]


def test_prepare_crsp_keeps_ciz_total_return_without_second_delist_adjustment():
    msf = pd.DataFrame({
        "permno": [1], "date": ["2025-01-31"], "ret": [-0.20],
        "prc": [8.0], "shrout": [100],
    })
    names = pd.DataFrame({
        "permno": [1], "namedt": ["2020-01-01"], "nameendt": [None],
        "siccd": [100], "common_stock": [True], "exchcd": [3],
    })
    delist = pd.DataFrame({"permno": [1], "dlstdt": ["2025-01-15"], "dlret": [-0.50]})
    ranges = pd.DataFrame({"industry": [1], "sic_lo": [100], "sic_hi": [199]})

    out = prepare_crsp(msf, names, ranges, delist, returns_include_delist=True)

    assert out["ret"].tolist() == pytest.approx([-0.20])
    assert out["industry"].tolist() == [1]


def test_link_uses_snapshot_valid_link_and_bounded_crsp_carry():
    ibes = pd.DataFrame({
        "ticker": ["AAA", "AAA"], "statpers": ["1990-01-18", "1990-02-15"],
        "fpedats": ["1990-12-31", "1990-12-31"], "numest": [5, 6],
        "numup": [2, 3], "numdown": [1, 1], "meanest": [1.0, 1.1],
    })
    links = pd.DataFrame({
        "ticker": ["AAA"], "permno": [1], "sdate": ["1990-01-01"],
        "edate": ["1990-01-31"], "score": [1],
    })
    stock = pd.DataFrame({
        "permno": [1], "date": ["1990-01-31"], "prc": [10], "mktcap": [1000], "industry": [1],
    })

    linked, rates = link_ibes(ibes, links, stock, max_carry_months=1)

    assert linked["month"].tolist() == [pd.Timestamp("1990-01-31")]
    assert linked["crsp_carried"].tolist() == [False]
    assert rates.loc[0, "link_rate"] == pytest.approx(0.5)


def test_link_rejects_crsp_characteristics_older_than_carry_limit():
    ibes = pd.DataFrame({
        "ticker": ["AAA"], "statpers": ["1992-01-15"], "numest": [5],
        "numup": [2], "numdown": [1], "meanest": [1.0], "fpedats": ["1992-12-31"],
    })
    links = pd.DataFrame({
        "ticker": ["AAA"], "permno": [1], "sdate": ["1990-01-01"],
        "edate": [None], "score": [1],
    })
    stock = pd.DataFrame({
        "permno": [1], "date": ["1990-01-31"], "prc": [10], "mktcap": [1000], "industry": [1],
    })

    linked, _ = link_ibes(ibes, links, stock, max_carry_months=12)

    assert linked.empty


def test_link_does_not_carry_missing_security_month_within_crsp_history():
    ibes = pd.DataFrame({
        "ticker": ["AAA"], "statpers": ["1990-02-15"], "numest": [5],
        "numup": [2], "numdown": [1], "meanest": [1.0], "fpedats": ["1990-12-31"],
    })
    links = pd.DataFrame({
        "ticker": ["AAA"], "permno": [1], "sdate": ["1990-01-01"],
        "edate": [None], "score": [1],
    })
    stock = pd.DataFrame({
        "permno": [1, 2], "date": ["1990-01-31", "1990-03-31"],
        "prc": [10, 20], "mktcap": [1000, 2000], "industry": [1, 2],
    })

    linked, _ = link_ibes(ibes, links, stock, max_carry_months=12)

    assert linked.empty


def test_link_blanks_carried_price_and_exposes_observation_age():
    ibes = pd.DataFrame({
        "ticker": ["AAA"], "statpers": ["1990-02-15"], "numest": [5],
        "numup": [2], "numdown": [1], "meanest": [1.0], "fpedats": ["1990-12-31"],
    })
    links = pd.DataFrame({
        "ticker": ["AAA"], "permno": [1], "sdate": ["1990-01-01"],
        "edate": [None], "score": [1],
    })
    stock = pd.DataFrame({
        "permno": [1], "date": ["1990-01-31"], "prc": [10],
        "mktcap": [1000], "industry": [1],
    })

    linked, _ = link_ibes(ibes, links, stock, max_carry_months=1)

    assert pd.isna(linked.loc[0, "prc"])
    assert linked.loc[0, "crsp_date"] == pd.Timestamp("1990-01-31")
    assert linked.loc[0, "price_age_months"] == 1
    assert linked.loc[0, "crsp_carried"]


def test_industry_coverage_includes_zeroes_and_flags_fewer_than_minimum():
    panel = pd.DataFrame({
        "month": ["2020-01-31"] * 5,
        "industry": [1] * 5,
        "permno": [1, 2, 3, 4, 5],
    })
    months = pd.Series(["2020-01-31", "2020-02-29"])

    coverage = industry_coverage(panel, months, min_firms=5)

    assert len(coverage) == 2 * 49
    january_industry_one = coverage.loc[
        coverage["month"].eq(pd.Timestamp("2020-01-31"))
        & coverage["industry"].eq(1)
    ].iloc[0]
    february_industry_one = coverage.loc[
        coverage["month"].eq(pd.Timestamp("2020-02-29"))
        & coverage["industry"].eq(1)
    ].iloc[0]
    assert january_industry_one["firms"] == 5
    assert not january_industry_one["low_coverage"]
    assert february_industry_one["firms"] == 0
    assert february_industry_one["low_coverage"]