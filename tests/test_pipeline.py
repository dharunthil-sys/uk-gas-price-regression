"""Tests use synthetic data generated here, not the real ONS/FRED data."""
import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import fetch_data  # noqa: E402
import model  # noqa: E402


def make_workbook() -> bytes:
    """Workbook shaped like an ONS release: notes sheet, title rows above the header."""
    days = pd.date_range("2022-01-01", "2023-12-31", freq="D")
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame({"Notes": ["Synthetic test workbook"]}).to_excel(xw, sheet_name="Cover", index=False)
        title = pd.DataFrame([["Table 1: System Average Price of gas", None], [None, None]])
        body = pd.DataFrame({"Date": days.strftime("%d/%m/%Y"), "SAP (pence per kWh)": np.linspace(5, 3, len(days))})
        title.to_excel(xw, sheet_name="Data", index=False, header=False)
        body.to_excel(xw, sheet_name="Data", index=False, startrow=3)
    return buf.getvalue()


def test_parse_sap_workbook_finds_offset_header():
    s = fetch_data.parse_sap_workbook(make_workbook())
    assert len(s) == 730
    assert s.index.min() == pd.Timestamp("2022-01-01")
    assert abs(s.iloc[0] - 5) < 1e-9


def test_parse_fred_handles_both_date_headers():
    for header in ("observation_date", "DATE"):
        csv = f"{header},DCOILBRENTEU\n2024-01-02,77.5\n2024-01-03,.\n2024-01-04,78.1\n".encode()
        s = fetch_data.parse_fred(csv, "DCOILBRENTEU")
        assert list(s.values) == [77.5, 78.1]


def test_build_monthly_drops_part_months():
    days = pd.date_range("2024-01-01", "2024-03-10", freq="D")
    s = pd.Series(1.0, index=days)
    m = fetch_data.build_monthly(s * 3, s * 80, s * 1.25)
    assert list(m.index.month) == [1, 2]
    assert abs(m["brent_gbp"].iloc[0] - 64) < 1e-9


def test_ols_recovers_known_elasticity():
    rng = np.random.default_rng(0)
    months = pd.date_range("2015-01-01", periods=120, freq="MS")
    brent = np.exp(rng.normal(4, 0.3, 120))
    season = 0.2 * np.cos(2 * np.pi * (months.month - 1) / 12)
    gas = np.exp(-1 + 0.8 * np.log(brent) + season + rng.normal(0, 0.05, 120))
    df = pd.DataFrame({"sap_p_per_kwh": gas, "brent_gbp": brent}, index=months)
    res = model.fit(df)
    b = res.coef[res.names.index("log_brent_gbp")]
    assert abs(b - 0.8) < 0.05
    assert res.r2 > 0.9
