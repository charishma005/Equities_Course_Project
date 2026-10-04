"""Phase 4 IC, orthogonalization, blending, and coverage tests."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ic import (  # noqa: E402
    apply_expanding_blend,
    expanding_blend_weights,
    monthly_information_coefficients,
    orthogonalize_revision,
    summarize_ic_by_horizon,
)


def test_monthly_ic_uses_t_signal_and_its_next_return():
    panel = pd.DataFrame({
        "month": [pd.Timestamp("2020-01-31")] * 5,
        "industry": range(1, 6),
        "mom_z": [1, 2, 3, 4, 5],
        "rev_z": [5, 4, 3, 2, 1],
        "rev_alt_z": [1, 2, 3, 4, 5],
        "next_return": [0.01, 0.02, 0.03, 0.04, 0.05],
    })

    ic = monthly_information_coefficients(panel).set_index("signal")

    assert ic.loc["mom", "spearman_ic"] == pytest.approx(1.0)
    assert ic.loc["rev", "spearman_ic"] == pytest.approx(-1.0)
    assert ic.loc["mom", "n_industries"] == 5


def test_rev_orthogonal_residual_is_cross_sectionally_orthogonal_to_mom():
    panel = pd.DataFrame({
        "month": [pd.Timestamp("2020-01-31")] * 5,
        "mom_z": [-2, -1, 0, 1, 2],
        "rev_z": [-3, -1, 0, 2, 4],
    })

    result = orthogonalize_revision(panel)

    assert result["rev_orth_z"].corr(result["mom_z"]) == pytest.approx(0.0, abs=1e-12)


def _blend_inputs():
    months = pd.date_range("2020-01-31", periods=4, freq="ME")
    rows = []
    for month_index, month in enumerate(months):
        for industry, mom in enumerate([-2.0, -1.0, 1.0, 2.0], start=1):
            rows.append({
                "month": month,
                "industry": industry,
                "mom_z": mom,
                "rev_z": mom * (0.5 + 0.1 * month_index) + [0.1, -0.2, 0.3, -0.1][industry - 1],
                "next_return": mom * 0.01,
            })
    panel = pd.DataFrame(rows)
    ic_rows = []
    for month_index, month in enumerate(months):
        ic_rows.extend([
            {"month": month, "signal": "mom", "spearman_ic": 0.1 + month_index * 0.01},
            {"month": month, "signal": "rev", "spearman_ic": 0.2 - month_index * 0.01},
        ])
    return panel, pd.DataFrame(ic_rows), months


def test_expanding_weights_at_t_ignore_ic_observations_at_t_and_after():
    panel, monthly_ic, months = _blend_inputs()
    initial = expanding_blend_weights(panel, monthly_ic, min_history=2)
    changed_ic = monthly_ic.copy()
    changed_ic.loc[changed_ic["month"].ge(months[2]), "spearman_ic"] = [-0.9, 0.9, -0.8, 0.8]
    changed = expanding_blend_weights(panel, changed_ic, min_history=2)

    initial_march = initial.loc[initial["month"].eq(months[2])].iloc[0]
    changed_march = changed.loc[changed["month"].eq(months[2])].iloc[0]
    assert initial_march["history_ic_months"] == 2
    assert np.isfinite(initial_march["mom_weight"])
    assert initial_march["mom_weight"] + initial_march["rev_weight"] == pytest.approx(1.0)
    assert initial_march["mom_weight"] == pytest.approx(changed_march["mom_weight"])
    assert initial_march["rev_weight"] == pytest.approx(changed_march["rev_weight"])


def test_recent_horizon_summary_reports_actual_missing_rev_months():
    months = pd.date_range("2025-03-31", periods=18, freq="ME")
    rows = []
    for month_index, month in enumerate(months):
        for industry in range(1, 4):
            rev = float(industry + month_index) if month_index < 10 else np.nan
            rows.append({
                "month": month,
                "industry": industry,
                "mom_z": float(industry),
                "rev_z": rev,
                "rev_alt_z": rev,
                "rev_orth_z": rev,
                "blend_z": rev,
                "mom": float(industry),
                "rev": rev,
                "rev_alt": rev,
                "next_return": np.nan if month_index == 17 else float(industry) / 100,
            })
    panel = pd.DataFrame(rows)
    ic = monthly_information_coefficients(panel)

    summary = summarize_ic_by_horizon(panel, ic)
    recent = summary.loc[summary["window"].eq("recent_18m")].set_index("signal")

    assert recent.loc["rev", "window_months"] == 18
    assert recent.loc["rev", "months_with_signal"] == 10
    assert recent.loc["rev", "ic_months"] == 10
    assert recent.loc["mom", "months_with_signal"] == 18
    assert recent.loc["mom", "ic_months"] == 17


def test_blend_requires_both_primary_signals():
    panel, monthly_ic, months = _blend_inputs()
    panel.loc[(panel["month"].eq(months[2])) & panel["industry"].eq(1), "rev_z"] = np.nan

    blended, _ = apply_expanding_blend(panel, monthly_ic, min_history=2)
    row = blended.loc[blended["month"].eq(months[2]) & blended["industry"].eq(1)].iloc[0]

    assert pd.isna(row["blend_z"])


def test_rev_sample_window_spans_only_months_with_rev_and_reports_nw_tstat():
    months = pd.date_range("2000-01-31", periods=30, freq="ME")
    rng = np.random.default_rng(0)
    rows = []
    for month_index, month in enumerate(months):
        has_rev = 5 <= month_index < 25
        for industry in range(1, 6):
            rows.append({
                "month": month, "industry": industry,
                "mom_z": rng.normal(), "rev_z": rng.normal() if has_rev else np.nan,
                "rev_alt_z": np.nan, "rev_orth_z": np.nan, "blend_z": np.nan,
                "next_return": rng.normal(0, 0.05),
            })
    panel = pd.DataFrame(rows)
    summary = summarize_ic_by_horizon(panel, monthly_information_coefficients(panel))
    rev_sample = summary.loc[summary["window"].eq("rev_sample")].set_index("signal")

    assert rev_sample.loc["mom", "window_start"] == months[5]
    assert rev_sample.loc["mom", "window_end"] == months[24]
    assert rev_sample.loc["mom", "ic_months"] == 20
    assert np.isfinite(rev_sample.loc["mom", "spearman_tstat_nw"])
