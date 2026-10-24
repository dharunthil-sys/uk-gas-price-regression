"""Regression of the UK wholesale gas price on the oil price and season.

Model (monthly data):

    log(SAP gas price) = b0 + b1 * log(Brent in GBP) + month-of-year effects + error

b1 is an elasticity: the % change in the UK gas price associated with a 1% change in
the oil price, holding the time of year fixed. Ordinary least squares with
heteroskedasticity-robust (HC1) standard errors, written out with numpy so the
calculation is visible.

Run:  python src/model.py   (after src/fetch_data.py)
Writes results/summary.md and charts to results/.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass
class OLSResult:
    names: list[str]
    coef: np.ndarray
    se: np.ndarray
    r2: float
    adj_r2: float
    n: int
    fitted: np.ndarray
    resid: np.ndarray

    def table(self) -> pd.DataFrame:
        t = self.coef / self.se
        return pd.DataFrame({"coef": self.coef, "robust_se": self.se, "t": t}, index=self.names)


def ols(X: np.ndarray, y: np.ndarray, names: list[str]) -> OLSResult:
    n, k = X.shape
    XtX_inv = np.linalg.inv(X.T @ X)
    coef = XtX_inv @ X.T @ y
    fitted = X @ coef
    resid = y - fitted
    meat = (X * resid[:, None] ** 2).T @ X
    cov = XtX_inv @ meat @ XtX_inv * n / (n - k)  # HC1
    ss_res = float(resid @ resid)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot
    adj = 1 - (1 - r2) * (n - 1) / (n - k)
    return OLSResult(names, coef, np.sqrt(np.diag(cov)), r2, adj, n, fitted, resid)


def design(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, list[str]]:
    month = pd.DatetimeIndex(df.index).month
    cols = {"const": np.ones(len(df)), "log_brent_gbp": np.log(df["brent_gbp"].to_numpy())}
    for m in range(2, 13):  # January is the baseline
        cols[f"month_{MONTHS[m - 1]}"] = (month == m).astype(float)
    names = list(cols)
    X = np.column_stack([cols[c] for c in names])
    y = np.log(df["sap_p_per_kwh"].to_numpy())
    return X, y, names


def fit(df: pd.DataFrame) -> OLSResult:
    X, y, names = design(df)
    # Drop month dummies that never occur (short samples), so X'X stays invertible
    keep = [i for i in range(X.shape[1]) if X[:, i].any()]
    return ols(X[:, keep], y, [names[i] for i in keep])


def rolling_elasticity(df: pd.DataFrame, window: int = 24) -> pd.Series:
    out = {}
    for end in range(window, len(df) + 1):
        res = fit(df.iloc[end - window:end])
        out[df.index[end - 1]] = res.coef[res.names.index("log_brent_gbp")]
    return pd.Series(out, name="elasticity")


def charts(df: pd.DataFrame, res: OLSResult, roll: pd.Series, out: Path) -> None:
    idx = pd.DatetimeIndex(df.index)

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(idx, df["sap_p_per_kwh"], color="#1f4e79", label="Actual SAP (p/kWh)")
    ax.plot(idx, np.exp(res.fitted), color="#c55a11", linestyle="--", label="Model fitted")
    ax.set_ylabel("Pence per kWh")
    ax.set_title("UK wholesale gas price: actual vs model")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(out / "actual_vs_fitted.png", dpi=150); plt.close(fig)

    fig, ax = plt.subplots(figsize=(6, 4.5))
    ax.scatter(df["brent_gbp"], df["sap_p_per_kwh"], s=14, color="#1f4e79", alpha=0.7)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("Brent crude, £ per barrel (log scale)")
    ax.set_ylabel("SAP gas, p/kWh (log scale)")
    ax.set_title("Monthly UK gas price vs oil price")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(out / "gas_vs_oil.png", dpi=150); plt.close(fig)

    month_effects = {"Jan": 0.0}
    for name, c in zip(res.names, res.coef):
        if name.startswith("month_"):
            month_effects[name[6:]] = c
    effects = pd.Series({m: month_effects.get(m, np.nan) for m in MONTHS})
    fig, ax = plt.subplots(figsize=(7, 3.5))
    ax.bar(effects.index, (np.exp(effects) - 1) * 100, color="#1f4e79")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_ylabel("% vs January, same oil price")
    ax.set_title("Seasonal pattern in UK gas prices")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(out / "seasonality.png", dpi=150); plt.close(fig)

    if not roll.empty:
        fig, ax = plt.subplots(figsize=(8, 3.5))
        ax.plot(pd.DatetimeIndex(roll.index), roll.values, color="#1f4e79")
        ax.axhline(0, color="black", linewidth=0.8)
        ax.set_ylabel("Elasticity to oil")
        ax.set_title("Rolling 24-month gas-to-oil elasticity")
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout(); fig.savefig(out / "rolling_elasticity.png", dpi=150); plt.close(fig)


def summary(df: pd.DataFrame, res: OLSResult, roll: pd.Series) -> str:
    t = res.table()
    b = t.loc["log_brent_gbp"]
    idx = pd.DatetimeIndex(df.index)
    resid = pd.Series(res.resid, index=idx)
    worst = resid.abs().sort_values(ascending=False).head(5)
    seasonal = t[t.index.str.startswith("month_")]["coef"]
    lines = [
        "# Results",
        "",
        f"Monthly data, {idx.min():%B %Y} to {idx.max():%B %Y} ({res.n} months).",
        "",
        "## Headline",
        "",
        f"- A 1% rise in the oil price (in pounds) is associated with a **{b.coef:.2f}%** change in the UK "
        f"wholesale gas price, holding the time of year fixed (robust t = {b.t:.1f}).",
        f"- Oil price and season together explain **{res.r2:.0%}** of the month-to-month variation in log gas prices "
        f"(adjusted R² {res.adj_r2:.2f}).",
    ]
    if not seasonal.empty:
        hi, lo = seasonal.idxmax()[6:], seasonal.idxmin()[6:]
        lines.append(f"- Relative to January, prices are highest in {hi} and lowest in {lo} at the same oil price.")
    if not roll.empty:
        lines.append(f"- The rolling 24-month elasticity ranged from {roll.min():.2f} to {roll.max():.2f}, "
                     f"so the gas-oil link is not stable over time.")
    lines += [
        "",
        "## Largest misses (model residuals)",
        "",
        "| Month | Actual p/kWh | Fitted p/kWh | Miss |",
        "|---|---|---|---|",
    ]
    for d in worst.index:
        i = idx.get_loc(d)
        lines.append(f"| {d:%b %Y} | {df['sap_p_per_kwh'].iloc[i]:.2f} | {np.exp(res.fitted[i]):.2f} | "
                     f"{(np.exp(res.resid[i]) - 1):+.0%} |")
    lines += [
        "",
        "## Coefficients",
        "",
        "| Term | Coefficient | Robust SE | t |",
        "|---|---|---|---|",
    ]
    lines += [f"| {n} | {r.coef:.3f} | {r.robust_se:.3f} | {r.t:.1f} |" for n, r in t.iterrows()]
    lines += [
        "",
        "![Actual vs fitted](actual_vs_fitted.png)",
        "",
        "![Gas vs oil](gas_vs_oil.png)",
        "",
        "![Seasonality](seasonality.png)",
        "",
        "![Rolling elasticity](rolling_elasticity.png)",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    df = pd.read_csv(ROOT / "data" / "monthly.csv", index_col="month", parse_dates=True)
    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    res = fit(df)
    roll = rolling_elasticity(df) if len(df) >= 36 else pd.Series(dtype=float)
    res.table().round(4).to_csv(out / "coefficients.csv")
    charts(df, res, roll, out)
    (out / "summary.md").write_text(summary(df, res, roll), encoding="utf-8")
    print((out / "summary.md").read_text(encoding="utf-8").split("## Largest")[0])


if __name__ == "__main__":
    main()
