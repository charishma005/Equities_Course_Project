"""End-to-end look-ahead and alignment tests for the signal panel (CLAUDE.md 1.1, 5).

Builds signals from synthetic Ken French returns and a synthetic linked
I/B/E/S panel, then checks that (a) every signal formed at month-end t is
paired with the industry return of month t+1, and (b) changing any data after
month T leaves every signal dated T or earlier unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.signals import (  # noqa: E402
    build_signals,
    horizon_coverage,
    industry_returns_long,
    mom_rev_cross_sectional_corr,
    plot_mom_rev_corr,
    signal_coverage,
    signal_summary,
)

MONTHS = pd.date_range("2015-01-31", "2017-12-31", freq="ME")
NAMES = {"Agric": 1, "Food": 2, "Other": 49}
SIGNAL_COLS = ["mom", "rev", "rev_alt", "mom_z", "rev_z", "rev_alt_z"]


def _sic_ranges() -> pd.DataFrame:
    return pd.DataFrame({
        "industry": [1, 2, 49], "short": list(NAMES), "name": list(NAMES),
        "sic_lo": [100, 2000, 4950], "sic_hi": [199, 2099, 4959],
    })


def _returns(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    data = {"date": MONTHS}
    for name in NAMES:
        data[name] = rng.normal(0.01, 0.05, len(MONTHS))
    return pd.DataFrame(data)


def _ibes(seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for month in MONTHS:
        for industry in NAMES.values():
            for k in range(5):
                rows.append({
                    "permno": industry * 100 + k, "month": month,
                    "fpedats": pd.Timestamp(f"{month.year}-12-31"),
                    "numest": 6, "numup": int(rng.integers(0, 4)),
                    "numdown": int(rng.integers(0, 4)),
                    "meanest": float(rng.normal(2, 0.3)), "prc": 20.0,
                    "mktcap": float(rng.uniform(100, 1000)), "industry": industry,
                })
    return pd.DataFrame(rows)


def _build(returns=None, ibes=None) -> pd.DataFrame:
    return build_signals(
        _ibes() if ibes is None else ibes,
        _returns() if returns is None else returns,
        _sic_ranges(), min_firms=5,
    )


def test_every_signal_row_is_paired_with_next_month_return():
    panel = _build()
    rets = industry_returns_long(_returns(), _sic_ranges()).set_index(["month", "industry"])["ret"]
    has_next = panel["month"] < MONTHS[-1]
    expected = [rets[(m + pd.offsets.MonthEnd(1), i)]
                for m, i in zip(panel.loc[has_next, "month"], panel.loc[has_next, "industry"])]
    assert panel.loc[has_next, "next_return"].to_numpy() == pytest.approx(np.array(expected))
    assert panel.loc[~has_next, "next_return"].isna().all()
    # each signal actually exists somewhere, so the check is not vacuous
    assert panel[["mom_z", "rev_z", "rev_alt_z"]].notna().any().all()


def test_signals_do_not_depend_on_future_data():
    cutoff = pd.Timestamp("2016-06-30")
    base = _build()

    returns = _returns()
    future = returns["date"] > cutoff
    returns.loc[future, list(NAMES)] = returns.loc[future, list(NAMES)] * -5 + 0.3
    ibes = _ibes()
    later = ibes["month"] > cutoff
    ibes.loc[later, ["numup", "meanest", "mktcap"]] = [5, 99.0, 1.0]
    shocked = _build(returns=returns, ibes=ibes)

    cols = ["month", "industry"] + SIGNAL_COLS
    before = base.loc[base["month"] <= cutoff, cols].reset_index(drop=True)
    after = shocked.loc[shocked["month"] <= cutoff, cols].reset_index(drop=True)
    pd.testing.assert_frame_equal(before, after)
    # sanity: the shock did change later signals
    assert not base.loc[base["month"] > cutoff, "mom"].equals(
        shocked.loc[shocked["month"] > cutoff, "mom"])


def test_missing_revision_months_stay_missing_and_window_is_not_shifted():
    # Mirrors the real data: I/B/E/S-CRSP links end six months before the
    # last Ken French month, so REV is missing at the end of the sample.
    ibes = _ibes()
    ibes = ibes.loc[ibes["month"] <= pd.Timestamp("2017-06-30")]
    panel = _build(ibes=ibes)

    late = panel["month"] > pd.Timestamp("2017-06-30")
    assert panel.loc[late, ["rev", "rev_z", "rev_alt", "rev_alt_z"]].isna().all().all()
    assert panel.loc[late, "mom_z"].notna().all()

    cov = horizon_coverage(panel).set_index(["window", "signal"])
    recent = cov.loc["recent_18m"]
    assert recent.loc["mom", "start"] == pd.Timestamp("2016-07-31")  # last 18 months
    assert recent.loc["mom", "end"] == pd.Timestamp("2017-12-31")
    assert recent.loc["mom", "months_with_signal"] == 18
    assert recent.loc["mom", "months_evaluable"] == 17               # no Jan-2018 return
    assert recent.loc["rev", "months_with_signal"] == 12             # Jul-2016..Jun-2017
    assert recent.loc["rev", "months_evaluable"] == 12


def test_phase3_outputs(tmp_path):
    panel = _build()
    cov = signal_coverage(panel)
    assert (cov["industries"] == 3).all()
    assert (cov["mom_available"] + cov["mom_missing"] == 3).all()
    summary = signal_summary(panel).set_index("signal")
    assert summary.loc["mom_z", "months_covered"] == len(MONTHS) - 11  # 11-month window
    corr = mom_rev_cross_sectional_corr(panel)
    assert corr["corr"].between(-1, 1).all()
    png = plot_mom_rev_corr(corr, tmp_path / "corr.png")
    assert png.exists() and png.stat().st_size > 0


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
