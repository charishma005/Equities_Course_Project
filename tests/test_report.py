"""Phase 9 tests: summary formatting and build from committed tables."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from src import report  # noqa: E402


def test_formatting_helpers():
    assert report.pct(0.0123) == "+1.2%"
    assert report.pct(-0.00004) == "0.0%"          # no "-0.0%"
    assert report.num(-0.0004, 3) == "0.000"
    assert report.num(float("nan")) == ""
    table = report.md_table(pd.DataFrame({"a": [1], "b": ["x"]}))
    assert table.splitlines() == ["| a | b |", "|---|---|", "| 1 | x |"]


@pytest.mark.skipif(not (config.TABLES / "alpha_with_without_umd.csv").exists(),
                    reason="Phase 7 tables not present")
def test_summary_builds_from_committed_tables_and_captions_every_figure():
    text = report.build_summary()
    for heading in ("Information coefficients", "Performance", "Factor attribution",
                    "Horizon splits", "Robustness grid", "Figures"):
        assert heading in text
    assert "do not implement" in text
    assert "Caption missing" not in text
