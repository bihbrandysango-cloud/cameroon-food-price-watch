# Cameroon Food Price Watch

A data pipeline that tracks maize, rice and cassava prices in Cameroonian markets every month and flags prices that are unusually high or unusually low for the time of year.

**Status:** in progress. Step 1 (data fetch) is built and tested.

## The problem

Food prices in Cameroon move sharply. In 2024 a kilo of white maize cost about 300 FCFA at the national median. By September 2026 it was about 150 FCFA. A jump hurts families who buy food. A crash hurts farmers who paid for seed and fertiliser at last year's prices. Both usually get noticed late.

Some rise every year is normal: prices climb in the lean season before harvest. The question this project answers is narrower: **is this market's price far from what it usually is in this month?**

## The data

[WFP food prices for Cameroon](https://data.humdata.org/dataset/wfp-food-prices-for-cameroon), published by the World Food Programme on the Humanitarian Data Exchange (HDX), licence CC BY-IGO.

- 77,711 price records, January 2005 to September 2026
- 83 markets in 9 regions, 55 commodities
- Retail and wholesale prices in FCFA, with local units (kg, 15 kg, 100 kg bags)

Limits worth knowing:
- WFP is collecting less. About 16,000 prices were recorded in 2023 and about 4,000 in the first nine months of 2026.
- Many markets in the Centre, Littoral and South-West have only a few years of history, so "normal for this month" can't be calculated for them yet.
- Limbe and the rest of Fako are not covered.

## How it works

| Step | What it does | Status |
|---|---|---|
| 1. Fetch | Checks HDX each month and saves the new file only when HDX has updated it. Validates columns, row count and prices before saving | Done |
| 2. Clean and store | dbt models in DuckDB: one unit (FCFA per kg), consistent market names, gaps marked | Next |
| 3. Community data | Prices collected by hand in Limbe markets, added as a second source | Planned |
| 4. Alerts | Price compared with the same month in past years, flagged both ways | Planned |
| 5. Forecast | Next month's price per market and commodity | Planned |
| 6. Dashboard | Power BI: map of markets, price trends, this month's alerts | Planned |

### Step 1 in detail

`src/ingest/fetch_wfp.py` asks the HDX API when the dataset last changed. If that matches the last saved version in `data/raw/manifest.json`, it stops. Otherwise it downloads the CSV, checks it, and records the fetch (time, HDX version, row count, date range, SHA-256 hash) in the manifest.

A GitHub Actions workflow (`.github/workflows/monthly-fetch.yml`) runs the tests and the fetch on the 10th of each month and commits new data.

**Known issue:** HDX's firewall answers scripted file downloads with a bot-check challenge, though its metadata API works. The script detects this and stops with a clear message instead of saving an empty file. Until there's an approved automated route, download the CSV from the HDX page and load it with `--from-file`.

## How to run

Requires Python 3.10 or later. Step 1 uses only the standard library.

```bash
pip install -r requirements-dev.txt
python -m pytest -q
python -m src.ingest.fetch_wfp                              # automatic
python -m src.ingest.fetch_wfp --from-file path/to/wfp_food_prices_cmr.csv   # manual download
```

## Credits

Data: World Food Programme, via HDX. The idea of a WFP price analysis came from [osulayman/nigeria-food-price-analysis](https://github.com/osulayman/nigeria-food-price-analysis). This project is written from scratch and adds automation, Cameroon coverage, community data and alerts.

Built by [Bih Brandy Sango](https://github.com/bihbrandysango-cloud).
