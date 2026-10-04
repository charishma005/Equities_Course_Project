"""Phase 6 tests: return timing, drift-adjusted turnover, costs, drawdowns."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import backtest  # noqa: E402

M = pd.date_range("2020-01-31", periods=5, freq="ME")


def _returns():
    # distinct returns per month so any off-by-one shows up
    return pd.DataFrame({1: [0.01, 0.10, -0.05, 0.02, 0.03],
                         2: [0.02, -0.10, 0.04, 0.01, -0.02]}, index=M)


def _holdings(months, weights, strategy="s", method="mv"):
    rows = []
    for m, (w1, w2) in zip(months, weights):
        rows += [{"month": m, "strategy": strategy, "method": method, "industry": 1, "weight": w1},
                 {"month": m, "strategy": strategy, "method": method, "industry": 2, "weight": w2}]
    return pd.DataFrame(rows)


def test_gross_return_uses_next_month_returns():
    res = backtest.strategy_returns(_holdings([M[0]], [(0.5, -0.5)]), _returns())
    row = res.iloc[0]
    assert row["return_month"] == M[1]
    assert row["gross_return"] == pytest.approx(0.5 * 0.10 - 0.5 * -0.10)


def test_turnover_is_against_drifted_prior_weights_and_cost_hits_next_return():
    res = backtest.strategy_returns(
        _holdings([M[0], M[1]], [(0.5, -0.5), (0.5, -0.5)]), _returns(), costs_bps=(20,))
    first, second = res.iloc[0], res.iloc[1]
    assert first["rebuild"] and first["turnover"] == pytest.approx(1.0)
    # prior book drifts with month-2 returns (M[1]): +10% and -10%
    g = 0.5 * 0.10 + -0.5 * -0.10
    drift = np.array([0.5 * 1.10, -0.5 * 0.90]) / (1 + g)
    expected = np.abs(np.array([0.5, -0.5]) - drift).sum()
    assert not second["rebuild"]
    assert second["turnover"] == pytest.approx(expected)
    assert second["net_return_20bps"] == pytest.approx(
        second["gross_return"] - 0.002 * expected)


def test_gap_month_forces_full_rebuild():
    res = backtest.strategy_returns(
        _holdings([M[0], M[2]], [(0.5, -0.5), (0.3, -0.3)]), _returns())
    assert res["rebuild"].tolist() == [True, True]
    assert res["turnover"].tolist() == pytest.approx([1.0, 0.6])


def test_unobserved_next_return_gives_nan():
    res = backtest.strategy_returns(_holdings([M[4]], [(0.5, -0.5)]), _returns())
    assert pd.isna(res.iloc[0]["gross_return"])


def test_max_drawdown():
    r = pd.Series([0.10, -0.20, 0.05, -0.10, 0.30])
    wealth = np.cumprod(1 + r.to_numpy())
    peak = np.maximum.accumulate(np.concatenate([[1], wealth]))[1:]
    assert backtest.max_drawdown(r) == pytest.approx((wealth / peak - 1).min())
    assert backtest.max_drawdown(pd.Series([0.01, 0.02])) == pytest.approx(0.0)


def test_performance_table_windows_and_sharpe():
    rng = np.random.default_rng(0)
    months = pd.date_range("2008-01-31", periods=60, freq="ME")
    returns = pd.DataFrame(rng.normal(0.01, 0.05, (61, 2)),
                           index=pd.date_range("2008-01-31", periods=61, freq="ME"),
                           columns=[1, 2])
    h = pd.concat([_holdings(months, [(0.5, -0.5)] * 60, strategy=s) for s in ("a", "b")])
    res = backtest.strategy_returns(h, returns)
    perf = backtest.performance_table(res, months[-1])
    full = perf.loc[perf["strategy"].eq("a") & perf["window"].eq("full")].iloc[0]
    gross = res.loc[res["strategy"].eq("a"), "gross_return"]
    assert full["sharpe_gross"] == pytest.approx(gross.mean() / gross.std() * np.sqrt(12))
    post = perf.loc[perf["strategy"].eq("a") & perf["window"].eq("post_2010")].iloc[0]
    assert post["months"] == 36
    recent = perf.loc[perf["strategy"].eq("a") & perf["window"].eq("recent_18m")].iloc[0]
    assert recent["months"] == 18
