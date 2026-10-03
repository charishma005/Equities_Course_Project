"""Offline tests for importing WRDS web-query downloads."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.import_wrds_files import identify, normalize, parse_dates  # noqa: E402


def test_ibes_uppercase_web_query_columns():
    raw = pd.DataFrame({
        "TICKER": ["AAPL ", "MSFT"], "CUSIP": ["03783310", "59491810"],
        "STATPERS": ["1990-01-18", "1990-01-18"], "FPEDATS": [19900930, 19900630],
        "NUMEST": [10, 8], "NUMUP": [2, 1], "NUMDOWN": [1, 0],
        "MEANEST": [1.5, 2.0], "MEDEST": [1.5, 2.0], "STDEV": [0.1, 0.2],
    })
    name, df = normalize(raw)
    assert name == "ibes_statsum"
    assert list(df.columns)[:4] == ["ticker", "cusip", "statpers", "fpedats"]
    assert df["statpers"].iloc[0] == pd.Timestamp("1990-01-18")
    assert df["fpedats"].iloc[0] == pd.Timestamp("1990-09-30")
    assert df["ticker"].iloc[0] == "AAPL"


def test_ibes_measure_and_fpi_filters_applied_when_present():
    # Same column layout as the team's actual WRDS web-query download
    raw = pd.DataFrame({
        "TICKER": ["A", "A", "B"], "CUSIP": ["1", "1", "2"], "OFTIC": ["A", "A", "B"],
        "STATPERS": ["1990-01-18"] * 3, "MEASURE": ["EPS", "EPS", "EPS"],
        "FPI": [1, 2, 1], "NUMEST": [3, 3, 4], "NUMUP": [1, 1, 0], "NUMDOWN": [0, 0, 1],
        "MEDEST": [1.0, 1.1, 2.0], "MEANEST": [1.0, 1.1, 2.0], "STDEV": [0.1, 0.1, 0.2],
        "FPEDATS": ["1990-12-31", "1991-12-31", "1990-12-31"],
    })
    name, df = normalize(raw)
    assert name == "ibes_statsum"
    assert df["ticker"].tolist() == ["A", "B"]  # FPI=2 row dropped


def test_unrecognized_file_is_skipped_not_fatal(tmp_path, capsys):
    from src.import_wrds_files import main
    p = tmp_path / "ids.csv"
    pd.DataFrame({"TICKER": ["A"], "OFTIC": ["A"], "STATPERS": ["1990-01-18"],
                  "MEASURE": ["EPS"], "FPI": [1]}).to_csv(p, index=False)
    main([p])
    assert "SKIPPED" in capsys.readouterr().out


def test_combined_crsp_web_download_split_into_three_tables(tmp_path, monkeypatch):
    import config
    from src.import_wrds_files import main
    monkeypatch.setattr(config, "DATA_RAW", tmp_path / "raw")
    p = tmp_path / "crsp.csv"
    pd.DataFrame({
        "PERMNO": [10001, 10001, 10002], "date": ["1990-01-31", "1990-02-28", "1990-01-31"],
        "SHRCD": [11, 11, 10], "EXCHCD": [1, 1, 3], "SICCD": [4920, 4920, "Z"],
        "PRC": [-10.0, 10.5, 20.0], "RET": ["0.01", "C", "0.02"], "SHROUT": [100, 100, 50],
        "DLRET": [None, -0.3, None],
    }).to_csv(p, index=False)
    main([p])
    msf = pd.read_parquet(tmp_path / "raw" / "crsp_msf.parquet")
    names = pd.read_parquet(tmp_path / "raw" / "crsp_msenames.parquet")
    dl = pd.read_parquet(tmp_path / "raw" / "crsp_msedelist.parquet")
    assert len(msf) == 3 and msf["ret"].isna().sum() == 1
    assert names.loc[0, "namedt"] == pd.Timestamp("1990-01-01")
    assert names.loc[0, "nameendt"] == pd.Timestamp("1990-01-31")
    assert dl[["permno", "dlret"]].values.tolist() == [[10001, -0.3]]
    assert dl["dlstdt"].iloc[0] == pd.Timestamp("1990-02-28")


def test_crsp_ret_letter_codes_become_nan():
    raw = pd.DataFrame({"PERMNO": [1, 1], "date": ["19900131", "19900228"],
                        "RET": ["0.05", "C"], "PRC": [-10.0, 11.0], "SHROUT": [100, 100]})
    name, df = normalize(raw)
    assert name == "crsp_msf"
    assert df["ret"].isna().tolist() == [False, True]


def test_msenames_not_mistaken_for_other():
    cols = ["permno", "namedt", "nameendt", "siccd", "shrcd", "exchcd", "ticker"]
    assert identify(cols) == "crsp_msenames"


def test_unknown_columns_raise():
    with pytest.raises(ValueError):
        identify(["foo", "bar"])


def test_parse_dates_keeps_blank_end_dates():
    out = parse_dates(pd.Series(["2001-05-01", None]))
    assert out.iloc[0] == pd.Timestamp("2001-05-01") and pd.isna(out.iloc[1])
