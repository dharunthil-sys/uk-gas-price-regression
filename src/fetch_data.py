"""Download the raw data used by the analysis.

Sources
-------
- UK System Average Price (SAP) of gas, daily, pence per kWh.
  Office for National Statistics, "System Average Price (SAP) of gas" dataset
  (published from National Gas Transmission data):
  https://www.ons.gov.uk/economy/economicoutputandproductivity/output/datasets/systemaveragepricesapofgas
- Brent crude oil spot price, daily, US dollars per barrel (FRED series DCOILBRENTEU,
  source: U.S. Energy Information Administration).
- US dollars to one British pound, daily (FRED series DEXUSUK, source: Federal Reserve).

Run:  python src/fetch_data.py
Writes the raw files to data/raw/ and a tidy monthly table to data/monthly.csv.
"""
from __future__ import annotations

import io
import re
import sys
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

ONS_PAGE = "https://www.ons.gov.uk/economy/economicoutputandproductivity/output/datasets/systemaveragepricesapofgas"
ONS_FALLBACK = (
    "https://www.ons.gov.uk/file?uri=%2Feconomy%2Feconomicoutputandproductivity%2Foutput%2Fdatasets"
    "%2Fsystemaveragepricesapofgas%2F2026%2Fsystemaveragepriceofgasdataset221026.xlsx"
)
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
HEADERS = {"User-Agent": "Mozilla/5.0 (uk-gas-price-regression; github.com/dharunthil-sys)"}


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def latest_ons_xlsx_url() -> str:
    """The ONS page lists one xlsx per edition; take the first (newest) link."""
    try:
        html = get(ONS_PAGE).decode("utf-8", "replace")
        links = re.findall(r'href="(/file\?uri=[^"]*systemaveragepricesapofgas[^"]*\.xlsx)"', html)
        if links:
            return "https://www.ons.gov.uk" + links[0].replace("&amp;", "&")
    except Exception as exc:  # network or page layout change
        print(f"Could not read ONS page ({exc}); using known file URL", file=sys.stderr)
    return ONS_FALLBACK


def parse_sap_workbook(content: bytes) -> pd.Series:
    """Find the daily SAP series in the ONS workbook without assuming its exact layout.

    Looks through every sheet for a header row with a date column and a numeric price
    column, so a moved header or renamed sheet in a future edition doesn't break the run.
    """
    sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None)
    best: pd.Series | None = None
    for name, raw in sheets.items():
        for header_row in range(min(30, len(raw))):
            header = ["" if pd.isna(x) else str(x).strip().lower() for x in raw.iloc[header_row]]
            date_cols = [i for i, h in enumerate(header) if "date" in h]
            if not date_cols:
                continue
            body = raw.iloc[header_row + 1:]
            dates = pd.to_datetime(body.iloc[:, date_cols[0]], errors="coerce", dayfirst=True)
            if dates.notna().sum() < 100:
                continue
            for j, h in enumerate(header):
                if j == date_cols[0]:
                    continue
                values = pd.to_numeric(body.iloc[:, j], errors="coerce")
                looks_like_price = any(k in h for k in ("sap", "price", "pence", "kwh"))
                if values.notna().sum() >= 100 and (looks_like_price or best is None):
                    series = pd.Series(values.values, index=dates.values, name="sap_p_per_kwh")
                    series = series[series.index.notna() & series.notna()].sort_index()
                    if looks_like_price:
                        print(f"Using sheet '{name}', column '{raw.iloc[header_row, j]}' ({len(series)} days)")
                        return series[~series.index.duplicated()]
                    best = series
    if best is None:
        raise ValueError("No daily date + price table found in the ONS workbook")
    return best[~best.index.duplicated()]


def parse_fred(content: bytes, series_id: str) -> pd.Series:
    df = pd.read_csv(io.BytesIO(content))
    date_col = df.columns[0]  # 'observation_date' (current) or 'DATE' (older files)
    s = pd.to_numeric(df[series_id], errors="coerce")
    s.index = pd.to_datetime(df[date_col])
    return s.dropna()


def build_monthly(sap: pd.Series, brent_usd: pd.Series, usd_per_gbp: pd.Series) -> pd.DataFrame:
    monthly = pd.DataFrame({
        "sap_p_per_kwh": sap.resample("MS").mean(),
        "brent_usd": brent_usd.resample("MS").mean(),
        "usd_per_gbp": usd_per_gbp.resample("MS").mean(),
        "sap_days": sap.resample("MS").count(),
    })
    monthly["brent_gbp"] = monthly["brent_usd"] / monthly["usd_per_gbp"]
    # Keep complete months only, so a part-month at the end doesn't skew the fit
    monthly = monthly[monthly["sap_days"] >= 20].dropna()
    monthly.index.name = "month"
    return monthly.round(4)


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    ons_url = latest_ons_xlsx_url()
    print(f"Downloading {ons_url}")
    ons = get(ons_url)
    (RAW / "ons_sap_gas.xlsx").write_bytes(ons)
    sap = parse_sap_workbook(ons)

    fred = {}
    for sid in ("DCOILBRENTEU", "DEXUSUK"):
        content = get(FRED.format(series=sid))
        (RAW / f"{sid}.csv").write_bytes(content)
        fred[sid] = parse_fred(content, sid)

    monthly = build_monthly(sap, fred["DCOILBRENTEU"], fred["DEXUSUK"])
    monthly.to_csv(ROOT / "data" / "monthly.csv")
    (ROOT / "data" / "SOURCE_URLS.txt").write_text(
        f"ONS SAP gas: {ons_url}\n" + "".join(f"FRED {s}: {FRED.format(series=s)}\n" for s in fred), encoding="utf-8")
    print(f"Wrote {len(monthly)} months ({monthly.index.min():%b %Y} to {monthly.index.max():%b %Y})")


if __name__ == "__main__":
    main()
