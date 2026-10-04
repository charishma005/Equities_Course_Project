"""Phase 7 tests: factor loading, month alignment, Newey-West regressions."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import attribution  # noqa: E402

DATES = pd.date_range("2000-01-31", periods=240, freq="ME")


def _factors(seed=0):
    rng = np.random.default_rng(seed)
    ff5 = pd.DataFrame(rng.normal(0, 0.04, (len(DATES), 5)), columns=attribution.FF5)
    ff5.insert(0, "date", DATES)
    ff5["RF"] = 0.002
    umd = pd.DataFrame({"date": DATES, "Mom": rng.normal(0.005, 0.05, len(DATES))})
    strev = pd.DataFrame({"date": DATES, "ST_Rev": rng.normal(0, 0.03, len(DATES))})
    return attribution.load_factors(ff5, umd, strev)


def _results(factors, alpha=0.004, beta_umd=0.5, seed=1, strategies=("s",)):
    rng = np.random.default_rng(seed)
    rows = []
    for s in strategies:
        for d in factors["date"].iloc[1:]:
            f = factors.set_index("date").loc[d]
            r = alpha + beta_umd * f["UMD"] + 0.2 * f["Mkt-RF"] + rng.normal(0, 0.01)
            rows.append({"strategy": s, "method": "mv", "month": d - pd.offsets.MonthEnd(1),
                         "return_month": d, "gross_return": r, "net_return_20bps": r})
    return pd.DataFrame(rows)


def test_load_factors_renames_momentum_and_reversal_columns():
    f = _factors()
    assert {"UMD", "ST_Rev", "RF", *attribution.FF5} <= set(f.columns)
    assert f["date"].iloc[0] == pd.Timestamp("2000-01-31")


def test_regression_recovers_alpha_and_umd_loading():
    f = _factors()
    res = attribution.factor_regressions(_results(f), f)
    row = res.loc[res["window"].eq("full") & res["spec"].eq("ff5_umd")].iloc[0]
    assert row["alpha_monthly"] == pytest.approx(0.004, abs=0.002)
    assert row["alpha_ann"] == pytest.approx(row["alpha_monthly"] * 12)
    assert row["beta_UMD"] == pytest.approx(0.5, abs=0.05)
    assert row["alpha_t"] > 2
    assert row["n"] == len(DATES) - 1


def test_dropping_umd_moves_momentum_return_into_alpha():
    f = _factors()
    res = attribution.factor_regressions(_results(f, alpha=0.0, beta_umd=0.8), f)
    full = res.loc[res["window"].eq("full")].set_index("spec")
    # UMD has a positive mean, so omitting it inflates alpha
    assert full.loc["ff5", "alpha_ann"] > full.loc["ff5_umd", "alpha_ann"] + 0.01
    comp = attribution.umd_comparison(res)
    assert {"alpha_t_ff5_umd", "alpha_t_ff5", "passes_criterion"} <= set(comp.columns)
    assert set(comp["passes_criterion"]) <= {"yes", "no", "n/a", "low power"}
    recent = comp.loc[comp["window"].eq("recent_18m"), "passes_criterion"]
    assert (recent == "low power").all()


def test_alignment_is_same_calendar_month_and_missing_months_raise():
    f = _factors()
    res = _results(f)
    merged = attribution.align(res, f)
    first = merged.iloc[0]
    assert first["UMD"] == pytest.approx(f.set_index("date").loc[first["return_month"], "UMD"])
    shifted = f.copy()
    shifted["date"] = shifted["date"] + pd.offsets.MonthEnd(1)   # off by one month
    shifted = shifted.iloc[:-1]
    with pytest.raises(ValueError):
        attribution.align(res, shifted.iloc[5:])


def test_short_windows_report_nan_instead_of_failing():
    f = _factors()
    res = _results(f).iloc[:5]
    out = attribution.nw_regression(res["net_return_20bps"],
                                    attribution.align(res, f)[attribution.SPECS["ff5_umd"]])
    assert out["n"] == 5 and np.isnan(out["alpha_t"])


def test_align_accepts_filtered_rows_with_non_default_index():
    # Regression: robustness passes subsets (e.g. one strategy's rows) whose
    # index does not start at 0; align used to crash under pandas 2.2.
    f = _factors()
    res = _results(f, strategies=("a", "b"))
    subset = res.loc[res["strategy"].eq("b")].iloc[10:50]
    assert subset.index[0] != 0
    merged = attribution.align(subset, f)
    assert len(merged) == 40
    assert (merged["date"] == merged["return_month"]).all()
