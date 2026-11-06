"""Step 5: forecast next month's price for every market, food and price type.

Run after `dbt build` (it reads the warehouse that dbt made):

    python -m src.forecast.forecast_prices

Three ways of guessing next month's price are tested on the past 12 months,
each one only allowed to see data from before the month it predicts:

1. naive           next month = this month
2. seasonal naive  next month = this month x how much the price moved
                   between the same two months last year
3. model           a gradient-boosted tree model trained on every market at
                   once, using recent price moves, last year's move, the
                   national trend for that food, the month, food and region

The backtest scores go to reports/forecast_backtest.json, so the README can
say honestly whether the model beats the simple guesses. The model then makes
the real forecast for the next month, with a likely range taken from its own
backtest errors, and compares it with the seasonal "normal" (same rules as
fct_price_alerts) to give an early warning.

Outputs: table forecast_next_month in the warehouse, and
data/outputs/forecast_next_month.csv.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

REPO_ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE = REPO_ROOT / "data" / "warehouse" / "food_prices.duckdb"
OUTPUT_CSV = REPO_ROOT / "data" / "outputs" / "forecast_next_month.csv"
BACKTEST_JSON = REPO_ROOT / "reports" / "forecast_backtest.json"

SERIES = ["market_code", "commodity_code", "price_type"]
BACKTEST_MONTHS = 12
# Same rules as the dbt alert model (transform/dbt_project.yml)
HISTORY_WINDOW_YEARS = 5
MIN_YEARS_HISTORY = 3
WATCH, ALERT = 0.20, 0.40

FEATURES = [
    "lag1_change", "lag2_change", "lag3_change", "last_year_next_change",
    "national_change", "target_month", "commodity_code", "region_code", "is_retail",
]
CATEGORICAL = ["commodity_code", "region_code"]

log = logging.getLogger("forecast")


def load_prices(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Monthly prices with suspect ones left out, as in the alert model."""
    return con.sql("""
        select market_code, market, region_code, region, commodity_code, commodity,
               price_type, standard_unit, price_month, price_per_unit
        from fct_monthly_prices
        where not is_suspect_price
    """).df()


def build_features(prices: pd.DataFrame) -> pd.DataFrame:
    """One row per series and month t, with features known at t and the target t+1.

    Every series is laid on a complete month-by-month calendar so "one month
    ago" really means one month ago; months with no price stay empty.
    Changes are in logs, so +0.1 means about 10% up whatever the price level.
    """
    prices = prices.assign(price_month=pd.to_datetime(prices["price_month"]).dt.to_period("M"))
    frames = []
    for key, s in prices.groupby(SERIES, sort=False):
        months = pd.period_range(s["price_month"].min(), s["price_month"].max(), freq="M")
        s = s.set_index("price_month").reindex(months)
        s[SERIES] = key
        for col in ["market", "region_code", "region", "commodity", "standard_unit"]:
            s[col] = s[col].ffill().bfill()
        s["log_price"] = np.log(s["price_per_unit"])
        lp = s["log_price"]
        s["lag1_change"] = lp - lp.shift(1)
        s["lag2_change"] = lp - lp.shift(2)
        s["lag3_change"] = lp - lp.shift(3)
        # How the price moved from this month to next month a year ago
        s["last_year_next_change"] = lp.shift(11) - lp.shift(12)
        s["target_change"] = lp.shift(-1) - lp
        frames.append(s.rename_axis("price_month").reset_index())
    df = pd.concat(frames, ignore_index=True)

    # National trend: median price change for the same food and price type this month
    national = (
        df.groupby(["commodity_code", "price_type", "price_month"])["lag1_change"]
        .median().rename("national_change").reset_index()
    )
    df = df.merge(national, on=["commodity_code", "price_type", "price_month"], how="left")
    df["target_month"] = (df["price_month"] + 1).dt.month
    df["is_retail"] = (df["price_type"] == "retail").astype(int)
    df["region_code"] = df["region_code"].astype("category").cat.codes
    return df


def seasonal_naive_change(df: pd.DataFrame) -> pd.Series:
    """Last year's move for the same two months, or no change if unknown."""
    return df["last_year_next_change"].fillna(0.0)


def new_model() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        loss="absolute_error",  # robust to the odd wild price
        max_iter=300,
        learning_rate=0.05,
        min_samples_leaf=40,
        categorical_features=[FEATURES.index(c) for c in CATEGORICAL],
        random_state=0,
    )


def backtest(df: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    """Walk forward through the last BACKTEST_MONTHS months.

    For each month, train only on rows whose target month is earlier, then
    predict that month. This is how the model would have done in real use.
    """
    usable = df.dropna(subset=["log_price", "target_change"])
    last_origin = usable["price_month"].max()
    origins = pd.period_range(last_origin - BACKTEST_MONTHS + 1, last_origin, freq="M")

    results = []
    for origin in origins:
        # A row at month t has its answer at t+1, so only rows before the
        # origin month have answers that were already known
        train = usable[usable["price_month"] < origin]
        test = usable[usable["price_month"] == origin]
        if test.empty:
            continue
        model = new_model().fit(train[FEATURES], train["target_change"])
        results.append(pd.DataFrame({
            "origin": origin,
            "actual": test["target_change"].to_numpy(),
            "naive": 0.0,
            "seasonal_naive": seasonal_naive_change(test).to_numpy(),
            "model": model.predict(test[FEATURES]),
        }))
    res = pd.concat(results, ignore_index=True)

    def score(col: str) -> dict:
        pct_error = np.abs(np.expm1(res[col] - res["actual"]))
        return {
            "median_abs_pct_error": round(float(pct_error.median()), 4),
            "mean_abs_pct_error": round(float(pct_error.mean()), 4),
            "within_10_pct": round(float((pct_error <= 0.10).mean()), 4),
        }

    errors = res["model"] - res["actual"]
    # Months where the price really moved: does each method at least get the direction?
    big = res[res["actual"].abs() > np.log(1.10)]

    def direction(col: str) -> float:
        return round(float((np.sign(big[col]) == np.sign(big["actual"])).mean()), 4)

    summary = {
        "backtest_months": f"{origins[0] + 1} to {origins[-1] + 1}",
        "predictions": len(res),
        "share_unchanged": round(float((res["actual"].abs() < 1e-9).mean()), 4),
        "naive": score("naive"),
        "seasonal_naive": {**score("seasonal_naive"), "direction_right_on_big_moves": direction("seasonal_naive")},
        "model": {**score("model"), "direction_right_on_big_moves": direction("model")},
        "big_moves_over_10_pct": len(big),
        # Model errors (in log terms) that hold 80% of cases: used for the likely range
        "model_error_p10": round(float(errors.quantile(0.10)), 4),
        "model_error_p90": round(float(errors.quantile(0.90)), 4),
    }
    return summary, res


def seasonal_normal(prices: pd.DataFrame, target: pd.Period) -> pd.DataFrame:
    """Median price for the target's calendar month in the last few earlier years."""
    p = prices.assign(price_month=pd.to_datetime(prices["price_month"]).dt.to_period("M"))
    past = p[
        (p["price_month"].dt.month == target.month)
        & (p["price_month"].dt.year < target.year)
        & (p["price_month"].dt.year >= target.year - HISTORY_WINDOW_YEARS)
    ]
    return (
        past.groupby(SERIES)["price_per_unit"]
        .agg(normal_price="median", years_of_history="count")
        .reset_index()
    )


def alert_level(gap: float, years: int) -> str:
    if years < MIN_YEARS_HISTORY or pd.isna(gap):
        return "not enough history"
    if gap >= ALERT:
        return "alert high"
    if gap <= -ALERT:
        return "alert low"
    if gap >= WATCH:
        return "watch high"
    if gap <= -WATCH:
        return "watch low"
    return "normal"


def forecast_next_month(df: pd.DataFrame, prices: pd.DataFrame, summary: dict) -> pd.DataFrame:
    """Train on everything, then forecast the month after the latest one."""
    usable = df.dropna(subset=["log_price", "target_change"])
    model = new_model().fit(usable[FEATURES], usable["target_change"])

    latest = df["price_month"].max()
    now = df[(df["price_month"] == latest) & df["log_price"].notna()].copy()
    change = model.predict(now[FEATURES])
    now["forecast_month"] = (latest + 1).to_timestamp().date()
    now["last_price"] = now["price_per_unit"].round(2)
    now["forecast_price"] = np.exp(now["log_price"] + change).round(2)
    now["forecast_low"] = np.exp(now["log_price"] + change + summary["model_error_p10"]).round(2)
    now["forecast_high"] = np.exp(now["log_price"] + change + summary["model_error_p90"]).round(2)

    out = now.merge(seasonal_normal(prices, latest + 1), on=SERIES, how="left")
    out["years_of_history"] = out["years_of_history"].fillna(0).astype(int)
    out["forecast_gap_from_normal"] = ((out["forecast_price"] - out["normal_price"]) / out["normal_price"]).round(3)
    out["forecast_alert_level"] = [
        alert_level(g, y) for g, y in zip(out["forecast_gap_from_normal"], out["years_of_history"])
    ]
    return out[[
        "forecast_month", "region", "market_code", "market", "commodity_code", "commodity",
        "price_type", "standard_unit", "last_price", "forecast_price", "forecast_low",
        "forecast_high", "normal_price", "years_of_history", "forecast_gap_from_normal",
        "forecast_alert_level",
    ]].sort_values(["region", "market", "commodity", "price_type"])


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with duckdb.connect(str(WAREHOUSE)) as con:
        prices = load_prices(con)
        df = build_features(prices)
        log.info("%s series, %s monthly rows", f"{df.groupby(SERIES).ngroups:,}", f"{len(df):,}")

        summary, _ = backtest(df)
        for name in ["naive", "seasonal_naive", "model"]:
            log.info("Backtest %-14s median error %.1f%%, within 10%%: %.0f%%", name,
                     100 * summary[name]["median_abs_pct_error"], 100 * summary[name]["within_10_pct"])

        forecast = forecast_next_month(df, prices, summary)
        con.register("forecast_df", forecast)
        con.sql("create or replace table forecast_next_month as select * from forecast_df")

    BACKTEST_JSON.parent.mkdir(parents=True, exist_ok=True)
    BACKTEST_JSON.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    forecast.to_csv(OUTPUT_CSV, index=False, lineterminator="\n")
    log.info("Forecast for %s: %s prices saved.", forecast["forecast_month"].iloc[0], f"{len(forecast):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
