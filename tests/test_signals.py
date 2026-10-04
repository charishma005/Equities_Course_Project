"""Timing and aggregation checks for signal construction."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.signals import (  # noqa: E402
    _zscore,
    attach_next_month_returns,
    industry_revisions,
    momentum_signal,
)


def test_zscore_preserves_missing_values_but_keeps_real_zeroes():
    values = pd.Series([1.0, 3.0, np.nan])

    standardized = _zscore(values, winsor=3.0)

    assert standardized.iloc[0] == pytest.approx(-1.0)
    assert standardized.iloc[1] == pytest.approx(1.0)
    assert pd.isna(standardized.iloc[2])
    assert _zscore(pd.Series([np.nan, np.nan]), winsor=3.0).isna().all()
    assert _zscore(pd.Series([2.0, 2.0, np.nan]), winsor=3.0).tolist()[:2] == [0.0, 0.0]


def test_momentum_uses_t_minus_11_to_t_minus_1_and_skips_month_t():
    # Jan-2020 .. Jan-2021. At t = Jan-2021 the window is Feb-2020 .. Dec-2020:
    # ten 1% months plus December's 50%; Jan-2020 (2%) and Jan-2021 (90%) excluded.
    returns = pd.DataFrame({
        "date": pd.date_range("2020-01-31", periods=13, freq="ME"),
        "Industry": [0.02] + [0.01] * 10 + [0.50, 0.90],
    })

    signal = momentum_signal(returns)
    january_2021 = signal.loc[signal["month"].eq(pd.Timestamp("2021-01-31")), "mom"].iloc[0]

    assert january_2021 == pytest.approx((1.01 ** 10) * 1.50 - 1)


def test_next_return_is_exactly_the_following_calendar_month():
    signals = pd.DataFrame({"month": [pd.Timestamp("2020-01-31")], "industry": [1]})
    returns = pd.DataFrame({
        "month": [pd.Timestamp("2020-01-31"), pd.Timestamp("2020-02-29")],
        "industry": [1, 1], "ret": [0.10, 0.20],
    })

    aligned = attach_next_month_returns(signals, returns)

    assert aligned["next_return"].iloc[0] == pytest.approx(0.20)


def test_revisions_are_market_cap_weighted_and_require_firm_coverage():
    ibes = pd.DataFrame({
        "permno": [1, 2, 3, 4, 5, 6],
        "month": ["2020-01-31"] * 6,
        "fpedats": ["2020-12-31"] * 6,
        "numest": [4] * 6, "numup": [3, 1, 2, 2, 2, 2],
        "numdown": [1, 1, 1, 1, 1, 1], "meanest": [2, 1, 1, 1, 1, 1],
        "prc": [10] * 6,
        "mktcap": [900, 100, 100, 100, 100, 100], "industry": [1] * 5 + [2],
    })

    # A prior-month observation is necessary for the alternative measure.
    prior = ibes.iloc[[0, 1, 2, 3, 4]].copy()
    prior["month"] = "2019-10-31"
    prior["meanest"] = 1
    current = ibes.iloc[:5].copy()
    current["meanest"] = [2, 1, 1, 1, 1]
    panel = pd.concat([prior, current], ignore_index=True)

    result = industry_revisions(panel, min_analysts=3, min_firms=5)
    value = result.loc[result["industry"].eq(1) & result["month"].eq(pd.Timestamp("2020-01-31")), "rev"]

    assert value.iloc[0] == pytest.approx((0.5 * 900 + 0.0 * 100 + 0.25 * 300) / 1300)
    assert result.loc[result["industry"].eq(2), "rev"].isna().all()


def test_alternative_revision_requires_analyst_coverage_at_both_dates():
    panel = pd.DataFrame({
        "permno": [1, 1],
        "month": ["2019-10-31", "2020-01-31"],
        "fpedats": ["2020-12-31", "2020-12-31"],
        "numest": [2, 3], "numup": [0, 2], "numdown": [0, 1],
        "meanest": [1.0, 2.0], "prc": [10.0, 10.0],
        "mktcap": [100.0, 100.0], "industry": [1, 1],
    })

    result = industry_revisions(panel, min_analysts=3, min_firms=1)
    current = result.loc[result["month"].eq(pd.Timestamp("2020-01-31"))]

    assert current["rev"].iloc[0] == pytest.approx(1 / 3)
    assert pd.isna(current["rev_alt"].iloc[0])