"""Phase 5 tests: EWMA covariance, alphas, capped holdings, lambda, timing."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from src import portfolio, risk  # noqa: E402


# --------------------------------------------------------------------------
# risk.py
# --------------------------------------------------------------------------
def _returns(n_months=80, n_ind=12, seed=0):
    rng = np.random.default_rng(seed)
    months = pd.date_range("2000-01-31", periods=n_months, freq="ME")
    data = rng.normal(0.01, 0.05, (n_months, n_ind)) + rng.normal(0, 0.03, (n_months, 1))
    return pd.DataFrame(data, index=months, columns=range(1, n_ind + 1))


def test_ewma_matches_direct_weighted_covariance():
    returns = _returns()
    covs = risk.ewma_covariances(returns, halflife=30, min_months=60)
    t = returns.index[70]
    x = returns.loc[:t].to_numpy()
    d = risk.ewma_decay(30)
    w = d ** np.arange(len(x))[::-1]
    w = w / w.sum()
    mean = w @ x
    direct = (x - mean).T @ ((x - mean) * w[:, None])
    assert covs[t] == pytest.approx(direct, rel=1e-9, abs=1e-12)
    assert risk.ewma_decay(30) ** 30 == pytest.approx(0.5)


def test_ewma_respects_min_history_and_ignores_future_returns():
    returns = _returns()
    covs = risk.ewma_covariances(returns, min_months=60)
    assert min(covs) == returns.index[59]
    t = returns.index[65]
    shocked = returns.copy()
    shocked.loc[shocked.index > t] *= 10
    assert risk.ewma_covariances(shocked, min_months=60)[t] == pytest.approx(covs[t])


def test_residual_volatility_is_vol_of_return_minus_industry_average():
    returns = _returns()
    cov = np.cov(returns.to_numpy(), rowvar=False, ddof=0)
    resid = returns.sub(returns.mean(axis=1), axis=0)
    expected = resid.std(ddof=0).to_numpy() * np.sqrt(12)
    assert risk.residual_volatility(cov) == pytest.approx(expected)


def test_returns_rebuilt_from_next_return_are_dated_t_plus_1():
    panel = pd.DataFrame({"month": [pd.Timestamp("2020-01-31")] * 2,
                          "industry": [1, 2], "next_return": [0.1, 0.2]})
    wide = risk.returns_from_signal_panel(panel)
    assert wide.index.tolist() == [pd.Timestamp("2020-02-29")]
    assert wide.loc["2020-02-29", 2] == pytest.approx(0.2)


# --------------------------------------------------------------------------
# portfolio.py building blocks
# --------------------------------------------------------------------------
def _cov_alpha(n=15, seed=1):
    rng = np.random.default_rng(seed)
    a = rng.normal(size=(n, n))
    cov = (a @ a.T / n + np.eye(n)) * 0.02
    alpha = rng.normal(0, 0.01, n)
    return cov, alpha - alpha.mean()


def test_alpha_is_ic_times_omega_times_z_and_demeaned():
    z = np.array([1.0, -1.0, 0.5])
    omega = np.array([0.1, 0.2, 0.3])
    alpha = portfolio.grinold_kahn_alpha(z, 0.05, omega)
    raw = 0.05 * omega * z
    assert alpha == pytest.approx(raw - raw.mean())
    assert alpha.sum() == pytest.approx(0.0, abs=1e-15)


def test_unconstrained_solution_satisfies_kkt_and_dollar_neutrality():
    cov, alpha = _cov_alpha()
    h = portfolio._unconstrained_dollar_neutral(alpha, cov)
    assert h.sum() == pytest.approx(0.0, abs=1e-12)
    gradient = alpha - 2 * cov @ h            # must be a constant vector (mu * 1)
    assert np.ptp(gradient) == pytest.approx(0.0, abs=1e-12)


def test_capped_holdings_respect_cap_and_beat_scaled_unconstrained():
    cov, alpha = _cov_alpha(n=20, seed=3)
    alpha[0] += 0.2                           # force one dominant position
    h, converged = portfolio.capped_mean_variance(alpha, cov, cap_frac=0.10)
    gross = np.abs(h).sum()
    assert converged
    assert h.sum() == pytest.approx(0.0, abs=1e-9)
    assert np.abs(h).max() <= 0.10 * gross * (1 + 1e-4)
    assert np.isclose(np.abs(h).max(), 0.10 * gross, rtol=1e-4)   # cap binds


def test_cap_not_binding_returns_unconstrained_solution():
    cov, alpha = _cov_alpha(n=40, seed=5)
    unconstrained = portfolio._unconstrained_dollar_neutral(alpha, cov)
    h, _ = portfolio.capped_mean_variance(alpha, cov, cap_frac=0.9)
    assert h == pytest.approx(unconstrained)


def test_calibration_hits_target_and_lambda_scales_holdings():
    cov, alpha = _cov_alpha()
    unit = portfolio._unconstrained_dollar_neutral(alpha, cov)
    h, lam, exante = portfolio.calibrate_to_target(unit, cov, target=0.05)
    assert exante == pytest.approx(0.05, rel=1e-12)
    assert h == pytest.approx(unit / lam)
    # h(lambda) is the closed form (1 / 2 lambda) Sigma^-1 (alpha - mu 1)
    ones = np.ones(len(alpha))
    mu = np.linalg.solve(cov, alpha).sum() / np.linalg.solve(cov, ones).sum()
    assert h == pytest.approx(np.linalg.solve(cov, alpha - mu * ones) / (2 * lam))


def test_diagonal_holdings_are_dollar_neutral():
    alpha = np.array([0.02, -0.01, 0.005, -0.015])
    omega = np.array([0.1, 0.2, 0.15, 0.3])
    h = portfolio.diagonal_holdings(alpha, omega)
    assert h.sum() == pytest.approx(0.0, abs=1e-15)


# --------------------------------------------------------------------------
# End-to-end monthly loop
# --------------------------------------------------------------------------
def _panel(n_months=90, n_ind=12, seed=7):
    rng = np.random.default_rng(seed)
    months = pd.date_range("2000-01-31", periods=n_months, freq="ME")
    rows = []
    for m in months:
        common = rng.normal(0, 0.03)
        for i in range(1, n_ind + 1):
            z = rng.normal()
            rows.append({"month": m, "industry": i, "mom_z": z,
                         "next_return": 0.01 * z + common + rng.normal(0, 0.04)})
    panel = pd.DataFrame(rows)
    panel.loc[panel["month"].eq(months[-1]), "next_return"] = np.nan
    return panel, months


def test_build_holdings_targets_risk_and_realized_return_is_h_dot_next_return():
    panel, months = _panel()
    holdings, diag = portfolio.build_holdings(panel, {"mom": "mom_z"}, ic_min_months=3)
    assert not diag.empty
    assert diag["exante_active_risk_ann"].to_numpy() == pytest.approx(0.05, rel=1e-6)
    assert diag["net_exposure"].abs().max() < 1e-8
    row = diag.loc[diag["method"].eq("mv")].iloc[0]
    h = holdings.loc[holdings["month"].eq(row["month"]) & holdings["method"].eq("mv")]
    nxt = panel.loc[panel["month"].eq(row["month"])].set_index("industry")["next_return"]
    assert row["realized_active_return_next"] == pytest.approx(
        (h.set_index("industry")["weight"] * nxt).sum())
    # first holdings month: needs 60 months of returns, which start at month 2
    assert diag["month"].min() >= months[60]
    assert pd.isna(diag.loc[diag["month"].eq(months[-1]),
                            "realized_active_return_next"]).all()


def test_holdings_at_t_do_not_depend_on_future_data():
    panel, months = _panel()
    t = months[75]
    base, _ = portfolio.build_holdings(panel, {"mom": "mom_z"}, ic_min_months=3)
    shocked = panel.copy()
    # Returns of months after t are next_return on signal months >= t.
    shocked.loc[shocked["month"] >= t, "next_return"] *= -3
    shocked.loc[shocked["month"] > t, "mom_z"] *= -1
    after, _ = portfolio.build_holdings(shocked, {"mom": "mom_z"}, ic_min_months=3)
    a = base.loc[base["month"].le(t)].reset_index(drop=True)
    b = after.loc[after["month"].le(t)].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)


def test_missing_signal_industries_get_no_position():
    panel, months = _panel()
    panel.loc[panel["industry"].eq(3), "mom_z"] = np.nan
    holdings, diag = portfolio.build_holdings(panel, {"mom": "mom_z"}, ic_min_months=3)
    assert not holdings["industry"].eq(3).any()
    assert (diag["n_industries"] == 11).all()


def test_shrinkage_keeps_variances_and_scales_covariances():
    cov, _ = _cov_alpha()
    shrunk = risk.shrink_covariance(cov, 0.5)
    assert np.diag(shrunk) == pytest.approx(np.diag(cov))
    off = ~np.eye(len(cov), dtype=bool)
    assert shrunk[off] == pytest.approx(0.5 * cov[off])
    assert risk.shrink_covariance(cov, 0.0) == pytest.approx(cov)
    with pytest.raises(ValueError):
        risk.shrink_covariance(cov, 1.5)


def test_build_holdings_uses_shrunk_covariance_for_risk():
    panel, months = _panel()
    _, raw = portfolio.build_holdings(panel, {"mom": "mom_z"}, ic_min_months=3,
                                      shrinkage=0.0)
    _, shrunk = portfolio.build_holdings(panel, {"mom": "mom_z"}, ic_min_months=3,
                                         shrinkage=0.5)
    # both hit the target under their own risk model, but lambdas differ
    assert shrunk["exante_active_risk_ann"].to_numpy() == pytest.approx(0.05, rel=1e-6)
    mv_raw = raw.loc[raw["method"].eq("mv"), "lambda"].to_numpy()
    mv_shr = shrunk.loc[shrunk["method"].eq("mv"), "lambda"].to_numpy()
    assert not np.allclose(mv_raw, mv_shr)


def test_beta_neutral_holdings_have_zero_beta_and_dollar_exposure():
    cov, alpha = _cov_alpha(n=20, seed=11)
    betas = risk.market_betas(cov)
    assert np.full(20, 1 / 20) @ betas == pytest.approx(1.0)   # market has beta 1
    h = portfolio._unconstrained_dollar_neutral(alpha, cov, extra=betas)
    assert h.sum() == pytest.approx(0, abs=1e-12) and betas @ h == pytest.approx(0, abs=1e-12)
    alpha_big = alpha.copy()
    alpha_big[0] += 0.2
    hc, ok = portfolio.capped_mean_variance(alpha_big, cov, extra=betas)
    assert ok and abs(betas @ hc) < 1e-8 and abs(hc.sum()) < 1e-8
    assert np.abs(hc).max() <= 0.10 * np.abs(hc).sum() * (1 + 1e-4)


def test_build_holdings_beta_neutral_option():
    panel, _ = _panel()
    _, diag = portfolio.build_holdings(panel, {"mom": "mom_z"}, ic_min_months=3,
                                       beta_neutral=True, methods=("mv",))
    assert set(diag["method"]) == {"mv"}
    assert diag["beta_exposure"].abs().max() < 1e-8
    assert diag["exante_active_risk_ann"].to_numpy() == pytest.approx(0.05, rel=1e-6)
