# Cameroon Food Price Watch

A data pipeline that tracks maize, rice and cassava prices in Cameroonian markets every month and flags prices that are unusually high or unusually low for the time of year.

**Status:** in progress. Step 1 (data fetch) is built and tested.

## The problem

Food prices in Cameroon move sharply. In 2024 a kilo of white maize cost about 300 FCFA at the national median. By September 2026 it was about 150 FCFA. A jump hurts families who buy food. A crash hurts farmers who paid for seed and fertiliser at last year's prices. Both usually get noticed late.

Some rise every year is normal: prices climb in the lean season before harvest. The question this project answers is narrower: **is this market's price far from what it usually is in this month?**

## The data

[WFP food prices for Cameroon](https://data.humdata.org/dataset/wfp-food-prices-for-cameroon), published by the World Food Programme on the Humanitarian Data Exchange (HDX), licence CC BY-IGO. The pipeline reads it through [HDX HAPI](https://hapi.humdata.org/docs), the Humanitarian API, which is built for programs like this one.

- 68,996 price records, January 2017 to September 2026 (HAPI's coverage; the HDX file goes back to 2005)
- 76 markets in 9 regions, 54 commodities
- Retail and wholesale prices in FCFA, with local units (kg, 15 kg, 100 kg bags)

Limits worth knowing:
- WFP is collecting less. About 16,000 prices were recorded in 2023 and about 4,000 in the first nine months of 2026.
- Many markets in the Centre, Littoral and South-West have only a few years of history, so "normal for this month" can't be calculated for them yet. Starting in 2017 also means the baseline covers about nine years, not twenty.
- Limbe and the rest of Fako are not covered, so the alerts don't apply there. The nearest WFP markets are Buea, Kumba and Mamfe.

## How it works

| Step | What it does | Status |
|---|---|---|
| 1. Fetch | Pulls prices from HDX HAPI each month, checks them, merges in new and corrected rows, and saves only when something changed | Done |
| 2. Clean and store | dbt models in DuckDB: every price in one unit, suspect prices flagged, gaps per market measured, 14 data tests | Done |
| 3. Community data | Prices collected by hand in Limbe markets, added as a second source | Later, after the core pipeline |
| 4. Alerts | Price compared with the same month in earlier years, flagged both ways | Done |
| 5. Forecast | Next month's price per market and food, with a likely range, backtested against simple guesses | Done |
| 6. Dashboard | Power BI: map of markets, price trends, this month's alerts | Planned |

### Step 1 in detail

`src/ingest/fetch_wfp.py` downloads prices from HAPI in pages of 2,000 rows and retries pages that arrive cut off. The first run takes the full history. After that it takes only the last six months, because WFP sometimes corrects recent prices, and merges them in: new rows are added and corrected rows replace old ones. Every price must be a positive number. If the result is identical to the last save, nothing is written. Each save is recorded in `data/raw/manifest.json` with the time, mode, row counts, date range and a SHA-256 hash.

A GitHub Actions workflow (`.github/workflows/monthly-fetch.yml`) runs the tests and the fetch on the 10th of each month and commits new data.

Why HAPI and not the HDX file link: HDX's firewall answers scripted file downloads with a bot check. HAPI is HDX's supported route for programs.

### Step 2 in detail

WFP records the same food in many sizes. In Maroua in September 2024, white maize was 350 FCFA per kg retail and 35,000 FCFA per 100 kg bag wholesale: the same price per kilo. A computer comparing 350 with 35,000 would get it badly wrong, so the dbt project in `transform/` puts every price into one unit before anything is compared.

| Table | What's in it |
|---|---|
| `stg_wfp__prices` (view) | Every raw price with its pack size read from the unit ("100 KG" is 100) and turned into FCFA per kg, per litre (oils, milk) or per piece (eggs). Daily wages are left out |
| `fct_monthly_prices` | One price per market, food, price type and month, next to the national median for the same food and month. Prices more than 3 times above or below that median, where at least 3 markets reported, are flagged `is_suspect_price` |
| `dim_markets` | One row per market: location, first and last month, months with prices, missing months, coverage, and whether it still reports |

Suspect prices are flagged, not deleted. Some are real: Kousseri, on the Chad border, recorded retail maize at 1,200 FCFA/kg in September 2024, 3.5 times the national median. Others are clearly recording mistakes: in April 2024 several Yaoundé and Douala markets list fresh cassava at 3,000 to 6,400 FCFA "per kg" and rice at 47,000, which look like bag prices entered with the unit "KG". 1,052 of 68,625 prices (1.5%) are flagged.

Coverage is uneven. 29 of 76 markets reported in September 2026, and the average market has prices in 78% of the months it was tracked. Maroua has 98%; Buea has 82%.

Data tests run on every build and stop the monthly job if they fail: required fields present, only known price types and units, no duplicate price for a market, food and month, no zero or negative prices, and wholesale prices per kg never more than 5 times the same market's retail price (which would mean a bag price wasn't divided).

### Step 4 in detail

Prices move with the seasons. In Maroua, white maize is usually about 400 FCFA/kg in August, just before the harvest, and 250 to 300 in November and December, just after it. Comparing every month with one yearly average would raise an alarm every August and miss trouble in December. So `fct_price_alerts` compares each price with the **same market, food, price type and calendar month in the last five earlier years**:

1. "Normal" is the median of those earlier prices. It uses earlier years only, never the same or later ones, so the alert only knows what someone would have known at the time. The median keeps one extreme year from moving it, and the five-year limit keeps old, pre-inflation prices from making today's look high.
2. With fewer than 3 earlier years for that month, the price is marked "not enough history" instead of guessed.
3. The gap from normal sets the level: within 20% is normal, 20 to 40% is watch, 40% or more is alert, both upwards and downwards. Thresholds live in `transform/dbt_project.yml`.
4. Suspect prices from step 2 are left out, so a recording mistake can't raise an alarm.

Checked against what happened in Maroua (retail white maize):

| Month | Price | Normal | Gap | Level |
|---|---|---|---|---|
| June 2024 (lean season) | 563 | 342 | +65% | alert high |
| February 2026 (price crash) | 134 | 350 | −62% | alert low |
| September 2026 | 200 | 334 | −40% | alert low |

Across maize, imported rice and fresh cassava, high alerts cluster in 2022 to 2024 (126, 161 and 145 a year), when food inflation was high. In 2026 that flips: 80 low alerts and 2 high, matching the maize price crash reported in the news. `rpt_current_alerts` lists the latest month's 158 prices outside the normal range, furthest first.

Limits, stated plainly:
- 78% of prices can't be judged yet, mostly because WFP's coverage only became dense from 2021. This share falls each year as history builds up.
- "Normal" isn't adjusted for general inflation. The five-year limit helps less than it sounds today: the data starts in 2017 and is thin before 2021, so for 2022 to 2024 the last five years are nearly all the history there is (it cut all-food high alerts from 2,832 to 2,670). It will matter more as years accumulate. The proper fix is adjusting prices with Cameroon's consumer price index, a planned improvement.

Two tests guard the logic: a market's first year for a food can never get an alert (proof that no future or same-year data is used), and every level must agree with its gap and the thresholds.

### Step 5 in detail

`src/forecast/forecast_prices.py` predicts next month's price for every market, food and price type, and checks itself honestly first. Three methods are compared over the last 12 months (October 2025 to September 2026, 5,136 predictions), each retrained every month on data from before the month it predicts:

| Method | How it guesses | Median error | Within 10% | Direction right when price moved >10% |
|---|---|---|---|---|
| Naive | Next month = this month | 3.2% | 69% | (never predicts a move) |
| Seasonal naive | This month × last year's move between the same two months | 5.6% | 63% | 29% |
| Model | Gradient-boosted trees (scikit-learn) on recent moves, last year's move, the national trend for that food, month, food and region | 3.4% | 70% | 58% |

The honest reading: one month ahead, **the model is no more accurate than assuming the price stays the same.** Prices are sticky: in 35% of cases the price didn't change at all. Where it helps is direction. In the 1,611 cases where the price moved more than 10%, the model called up or down correctly 58% of the time, against 29% for last year's pattern. Seasonal patterns alone are a poor guide in these years of inflation and then a crash.

So read the forecast as a **likely range**. The range comes from the model's own backtest errors and holds 80% of past outcomes (roughly 14% below to 18% above the forecast). Each forecast is then compared with the seasonal normal for the coming month, using the same rules as step 4, to give an early warning.

October 2026 forecast for retail white maize: prices are expected to stay far below normal across the north. Garoua (156 FCFA/kg against a normal 293), Ngaoundéré, Kaele, Kousseri and Banyo come out as alert low, and Maroua as watch low (201 against 325). That points to another hard month for farmers, not for buyers. Of 438 forecasts, 46 are alert or watch high, 89 alert or watch low, and 122 have too little history to judge.

Outputs: `data/outputs/forecast_next_month.csv` (also the `forecast_next_month` warehouse table) and `reports/forecast_backtest.json` with all the scores. Tests check that gaps in a series stay gaps, that features only use the past, that last year's move lines up with the month being forecast, and that the alert rules match dbt's.

## How to run

Requires Python 3.10 or later. Step 1 uses only the standard library; steps 2 to 5 need DuckDB, dbt, pandas and scikit-learn (`requirements.txt`). A virtual environment keeps them separate from other projects:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

HAPI asks each app to identify itself with base64 of `app_name:email`. Set it as an environment variable (and as the repository secret `HAPI_APP_IDENTIFIER` for GitHub Actions):

```bash
export HAPI_APP_IDENTIFIER=$(printf 'your-app-name:you@example.com' | base64)
```

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
python -m src.ingest.fetch_wfp           # update the last six months
python -m src.ingest.fetch_wfp --full    # rebuild the whole history

# Steps 2 to 4: build and test the warehouse (run from the repository root)
dbt build --project-dir transform --profiles-dir transform

# Step 5: backtest and forecast next month
python -m src.forecast.forecast_prices
```

The warehouse is one file, `data/warehouse/food_prices.duckdb`. It's rebuilt from `data/raw` on every run, so it isn't committed.

## Credits

Data: World Food Programme, via HDX. The idea of a WFP price analysis came from [osulayman/nigeria-food-price-analysis](https://github.com/osulayman/nigeria-food-price-analysis). This project is written from scratch and adds automation, Cameroon coverage, community data and alerts.

Built by [Bih Brandy Sango](https://github.com/bihbrandysango-cloud).
