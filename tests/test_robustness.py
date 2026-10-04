"""Phase 8 tests: grid layout, variant signals, scoring, stability tables."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from src import robustness  # noqa: E402

PANEL = ROOT / "data" / "processed" / "signals_phase4.parquet"


def test_grid_is_one_at_a_time_plus_full_heatmap():
    variants = robustness.grid_variants()
    ids = [v["id"] for v in variants]
    assert ids[0] == "base" and len(ids) == len(set(ids))
    for v in variants:
        changed = {k for k in config.GRID_BASE if v[k] != config.GRID_BASE[k]}
        if v["dimension"] == "heatmap":
            assert changed == {"mom_lookback", "cov_halflife"}
        elif v["dimension"] != "base":
            assert changed == {v["dimension"]}
    cells = {(v["mom_lookback"], v["cov_halflife"]) for v in variants
             if {k for k in config.GRID_BASE if v[k] != config.GRID_BASE[k]}
             <= {"mom_lookback", "cov_halflife"}}
    assert len(cells) == 9


@pytest.mark.skipif(not PANEL.exists(), reason="committed Phase 4 panel not present")
def test_momentum_rebuilt_from_next_return_matches_panel_at_12_months():
    panel = pd.read_parquet(PANEL)[robustness.PHASE3_COLUMNS]
    panel = panel.loc[panel["month"] >= "1960-01-31"].copy()
    panel["industry"] = panel["industry"].astype(int)
    full = pd.read_parquet(PANEL)[robustness.PHASE3_COLUMNS]
    full["industry"] = full["industry"].astype(int)
    rebuilt = robustness.with_momentum_lookback(full, 12)
    merged = panel.merge(rebuilt[["month", "industry", "mom"]], on=["month", "industry"],
                         suffixes=("", "_rebuilt")).dropna(subset=["mom", "mom_rebuilt"])
    assert len(merged) > 10000
    assert merged["mom"].to_numpy() == pytest.approx(merged["mom_rebuilt"].to_numpy(),
                                                     rel=1e-9, abs=1e-12)


def test_consensus_change_variant_swaps_rev_columns():
    panel = pd.DataFrame({c: [1.0] for c in robustness.PHASE3_COLUMNS})
    panel["month"], panel["industry"] = pd.Timestamp("2000-01-31"), 1
    panel["rev"], panel["rev_z"], panel["rev_alt"], panel["rev_alt_z"] = 0.1, 0.2, 0.3, 0.4
    settings = {**config.GRID_BASE, "rev_measure": "consensus_change"}
    out = robustness.variant_panel(panel, settings)
    assert out.loc[0, "rev"] == 0.3 and out.loc[0, "rev_z"] == 0.4


def test_remap_to_30_industries_uses_matched_crsp_sic():
    ibes = pd.DataFrame({"permno": [1, 2], "crsp_date": ["2020-01-31", "2020-01-31"],
                         "industry": [5, 5]})
    crsp = pd.DataFrame({"permno": [1, 2], "date": ["2020-01-31", "2020-01-31"],
                         "siccd": [150, 9999]})
    sic30 = pd.DataFrame({"industry": [1], "sic_lo": [100], "sic_hi": [199]})
    out = robustness.remap_to_30_industries(ibes, crsp, sic30)
    assert out["industry"].tolist() == [1, config.OTHER_INDUSTRY_30]


def _results(n=400, seed=0):
    rng = np.random.default_rng(seed)
    months = pd.date_range("1990-01-31", periods=n, freq="ME")
    r = rng.normal(0.003, 0.02, n)
    return pd.DataFrame({"strategy": "blend", "method": "mv", "month": months,
                         "return_month": months + pd.offsets.MonthEnd(1),
                         "gross_return": r, "turnover": 0.5,
                         "net_return_10bps": r - 0.0005, "net_return_20bps": r - 0.001,
                         "net_return_30bps": r - 0.0015})


def test_score_uses_fixed_window_and_cost_column():
    res = _results()
    s20 = robustness.score(res, 20, None)
    start, end = (pd.Timestamp(d) for d in config.ROBUSTNESS_WINDOW)
    window = res.loc[res["month"].between(start, end)]
    assert s20["months"] == len(window)
    expected = window["net_return_20bps"].mean() / window["net_return_20bps"].std() * np.sqrt(12)
    assert s20["sharpe_net"] == pytest.approx(expected)
    assert robustness.score(res, 30, None)["sharpe_net"] < s20["sharpe_net"]
    assert np.isnan(s20["alpha_t_ff5_umd"])


def test_annual_returns_compound_within_calendar_year():
    res = _results(n=24)
    out = robustness.annual_returns(res, "net_return_20bps")
    first_year = out.iloc[0]
    year_rows = res.loc[res["return_month"].dt.year.eq(first_year["year"]), "net_return_20bps"]
    assert first_year["net_return"] == pytest.approx(np.prod(1 + year_rows) - 1)
    assert first_year["months"] == len(year_rows)
