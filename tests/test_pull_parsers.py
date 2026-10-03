"""Offline tests for Phase 1 parsers and repo hygiene (no network needed)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pull_public import (  # noqa: E402
    fred_monthly_mean,
    parse_kf_monthly_tables,
    parse_siccodes,
    select_table,
)
from src.utils import to_month_end  # noqa: E402

KF_INDUSTRY_SAMPLE = """\
  This file was created by CMPT_IND_RETS using the 202408 CRSP database.

  Average Value Weighted Returns -- Monthly
,Agric,Food ,Other
192607,   2.37,   0.12, -99.99
192608,   2.23,   2.68,   1.50

  Average Equal Weighted Returns -- Monthly
,Agric,Food ,Other
192607,   1.00,   2.00,   3.00

  Average Value Weighted Returns -- Annual
,Agric,Food ,Other
  1927,  10.00,  20.00,  30.00
"""

FF5_SAMPLE = """\
This file was created using the 202408 CRSP database.
The 1-month TBill rate data until 202405 come from Ibbotson Associates.

,Mkt-RF,SMB,HML,RMW,CMA,RF
196307,   -0.39,   -0.41,   -0.97,    0.68,   -1.18,    0.27
196308,    5.07,   -0.80,    1.80,    0.36,   -0.35,    0.25

 Annual Factors: January-December
,Mkt-RF,SMB,HML,RMW,CMA,RF
  1964,   12.51,    0.34,   10.11,    0.30,    4.48,    3.54
"""

SIC_SAMPLE = """\
 1 Agric  Agriculture
          0100-0199 Agricultural production - crops
          0200-0299 Agricultural production - livestock

 2 Food   Food Products
          2000-2009 Food and kindred products
"""


def test_kf_industry_value_weighted_monthly_selected_and_decimal():
    tables = parse_kf_monthly_tables(KF_INDUSTRY_SAMPLE)
    assert len(tables) == 2  # two monthly tables; annual table ignored
    vw = select_table(tables, "Value Weighted Returns -- Monthly")
    assert list(vw.columns) == ["date", "Agric", "Food", "Other"]
    assert vw["date"].tolist() == [pd.Timestamp("1926-07-31"), pd.Timestamp("1926-08-31")]
    assert vw.loc[0, "Agric"] == pytest.approx(0.0237)
    assert np.isnan(vw.loc[0, "Other"])  # -99.99 -> NaN


def test_kf_ff5_first_table_monthly_only():
    ff5 = select_table(parse_kf_monthly_tables(FF5_SAMPLE))
    assert len(ff5) == 2
    assert ff5["RF"].iloc[1] == pytest.approx(0.0025)
    assert ff5["date"].iloc[-1] == pd.Timestamp("1963-08-31")


def test_siccodes_ranges():
    sic = parse_siccodes(SIC_SAMPLE)
    assert sic.shape == (3, 5)
    assert sic.iloc[0].to_dict() == {"industry": 1, "short": "Agric",
                                     "name": "Agriculture", "sic_lo": 100, "sic_hi": 199}
    assert sic.iloc[2]["industry"] == 2


def test_fred_monthly_mean_handles_missing_dot():
    csv = "DATE,BAA10Y\n2020-01-02,2.0\n2020-01-03,.\n2020-01-06,3.0\n2020-02-03,1.0\n"
    m = fred_monthly_mean(csv, "BAA10Y")
    assert m["date"].tolist() == [pd.Timestamp("2020-01-31"), pd.Timestamp("2020-02-29")]
    assert m["BAA10Y"].tolist() == [2.5, 1.0]


def test_to_month_end_yyyymm_and_dates():
    assert to_month_end(pd.Series([202402])).iloc[0] == pd.Timestamp("2024-02-29")
    assert to_month_end(pd.Series(pd.to_datetime(["2024-03-21"]))).iloc[0] == \
        pd.Timestamp("2024-03-31")


def test_raw_and_interim_data_are_gitignored():
    for p in ["data/raw/x.parquet", "data/interim/x.parquet", ".env"]:
        r = subprocess.run(["git", "check-ignore", "-q", p], cwd=ROOT)
        assert r.returncode == 0, f"{p} is not ignored by git"
