"""Tests for the forecast step, on small made-up price series."""

import numpy as np
import pandas as pd
import pytest

from src.forecast.forecast_prices import alert_level, build_features, seasonal_normal


def series(prices: list[float | None], start: str = "2024-01", market: int = 1) -> pd.DataFrame:
    months = pd.period_range(start, periods=len(prices), freq="M")
    rows = [
        {
            "market_code": market, "market": "Maroua", "region_code": "CM004", "region": "Far-North",
            "commodity_code": 67, "commodity": "Maize (white)", "price_type": "retail",
            "standard_unit": "kg", "price_month": m.to_timestamp(), "price_per_unit": p,
        }
        for m, p in zip(months, prices) if p is not None
    ]
    return pd.DataFrame(rows)


def test_missing_months_are_kept_as_gaps_not_skipped():
    # March has no price, so April's "one month ago" is empty, not February
    df = build_features(series([100, 110, None, 121]))
    april = df[df["price_month"] == pd.Period("2024-04", "M")].iloc[0]
    assert np.isnan(april["lag1_change"])
    assert april["lag2_change"] == pytest.approx(np.log(121 / 110))


def test_features_only_use_the_past_and_target_is_next_month():
    df = build_features(series([100, 200, 400]))
    feb = df[df["price_month"] == pd.Period("2024-02", "M")].iloc[0]
    assert feb["lag1_change"] == pytest.approx(np.log(2))       # Jan -> Feb, known in Feb
    assert feb["target_change"] == pytest.approx(np.log(2))     # Feb -> Mar, the answer
    assert feb["target_month"] == 3


def test_last_year_move_lines_up_with_the_month_being_forecast():
    # 13 months: Jan 2024 to Jan 2025. At Jan 2025 we forecast Feb 2025,
    # so the seasonal clue is last year's Jan -> Feb move (100 -> 150).
    prices = [100, 150] + [150] * 10 + [200]
    df = build_features(series(prices))
    jan25 = df[df["price_month"] == pd.Period("2025-01", "M")].iloc[0]
    assert jan25["last_year_next_change"] == pytest.approx(np.log(1.5))


def test_seasonal_normal_uses_only_recent_earlier_years():
    # October prices in 2018 to 2025; forecasting October 2026 must use 2021 to 2025 only
    rows = pd.concat([series([p], start=f"{y}-10") for y, p in zip(range(2018, 2026), [1, 1, 1, 10, 20, 30, 40, 50])])
    normal = seasonal_normal(rows, pd.Period("2026-10", "M")).iloc[0]
    assert normal["years_of_history"] == 5
    assert normal["normal_price"] == 30


@pytest.mark.parametrize("gap, years, level", [
    (0.65, 5, "alert high"), (-0.62, 3, "alert low"), (0.25, 4, "watch high"),
    (-0.37, 5, "watch low"), (0.05, 5, "normal"), (0.90, 2, "not enough history"),
])
def test_alert_levels_match_the_dbt_rules(gap, years, level):
    assert alert_level(gap, years) == level
