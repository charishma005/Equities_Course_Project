"""End-to-end checks for signal-date and next-return alignment."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.signals import build_signals  # noqa: E402


def test_signal_at_t_uses_only_returns_through_t_minus_1_and_targets_t_plus_1():
    dates = pd.date_range("2020-01-31", periods=4, freq="ME")
    returns = pd.DataFrame({
        "date": dates,
        "Agric": [0.10, 0.20, 0.30, 0.40],
        "Other": [0.01, 0.02, 0.03, 0.04],
    })
    sic_ranges = pd.DataFrame({
        "industry": [1], "short": ["Agric"], "sic_lo": [100], "sic_hi": [199],
    })
    ibes = pd.DataFrame(columns=[
        "permno", "month", "fpedats", "numest", "numup", "numdown", "meanest",
        "prc", "mktcap", "industry",
    ])

    signals = build_signals(ibes, returns, sic_ranges, lookback=3, skip=1)
    march = signals.loc[
        signals["month"].eq(pd.Timestamp("2020-03-31"))
        & signals["industry"].eq(1)
    ].iloc[0]

    assert march["mom"] == pytest.approx((1.10 * 1.20) - 1)
    assert march["next_return"] == pytest.approx(0.40)