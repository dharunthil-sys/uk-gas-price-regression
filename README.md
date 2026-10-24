# UK Gas Price Regression

How closely does the UK wholesale gas price follow the oil price, and how much of its movement is just the time of year?

This project regresses the monthly UK **System Average Price (SAP) of gas** on the **Brent crude oil price** (converted to pounds) and month-of-year effects, then checks whether the relationship holds steady over time.

**Results:** see [`results/summary.md`](results/summary.md) for the estimates, the months the model missed most, and the charts.

## Data

| Series | Frequency | Source |
|---|---|---|
| System Average Price of gas, p/kWh | Daily | [ONS, System Average Price (SAP) of gas](https://www.ons.gov.uk/economy/economicoutputandproductivity/output/datasets/systemaveragepricesapofgas) (National Gas Transmission data) |
| Brent crude spot price, $/barrel | Daily | [FRED DCOILBRENTEU](https://fred.stlouisfed.org/series/DCOILBRENTEU) (U.S. Energy Information Administration) |
| US dollars per pound | Daily | [FRED DEXUSUK](https://fred.stlouisfed.org/series/DEXUSUK) (Federal Reserve) |

Daily values are averaged to calendar months, and months with fewer than 20 days of gas prices are dropped. The data is downloaded fresh each month by a GitHub Actions workflow, so the results stay current; the exact files used are saved in `data/raw/` and their URLs in `data/SOURCE_URLS.txt`.

## Method

```
log(gas price) = b0 + b1 · log(Brent in £) + month-of-year effects + error
```

- **b1** is an elasticity: the % change in the gas price linked to a 1% change in the oil price, at the same time of year.
- Month dummies (January as the baseline) capture the winter heating premium.
- Ordinary least squares with heteroskedasticity-robust (HC1) standard errors, written out in numpy in [`src/model.py`](src/model.py) so each step is visible.
- A rolling 24-month regression shows whether the gas–oil link changes over time, for example during the 2021–22 European gas crisis, when gas prices moved far more than oil.

## Limitations

- This is an association, not a causal estimate: both prices respond to shared shocks such as the war in Ukraine.
- Monthly prices are strongly autocorrelated, so the standard errors are optimistic. A natural next step is Newey–West errors or a model in differences.
- Oil is only one driver. Storage levels, LNG imports, temperature and the European TTF price would all improve the fit.

## Run it yourself

```bash
pip install -r requirements.txt
python src/fetch_data.py   # downloads the data
python src/model.py        # fits the model, writes results/
pytest                     # tests on synthetic data
```
