"""Export the warehouse tables the Power BI report reads.

Run after `dbt build` and the forecast:

    python -m src.export.export_powerbi

Writes plain CSV files to powerbi/data/, one per table in the report's model.
Power BI reads them through the DataFolder parameter, so refreshing the report
after a monthly run picks up the new month.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE = REPO_ROOT / "data" / "warehouse" / "food_prices.duckdb"
OUT_DIR = REPO_ROOT / "powerbi" / "data"

# Plain-language labels for the report, matching the alert rules in dbt
DIRECTION = """
    case
        when alert_level like '%high' then 'Too expensive'
        when alert_level like '%low'  then 'Too cheap'
        when alert_level = 'normal'   then 'Normal'
        else 'Not enough history'
    end
"""
STRENGTH = """
    case
        when alert_level like 'alert%' then 'Alert'
        when alert_level like 'watch%' then 'Watch'
        else ''
    end
"""

QUERIES = {
    "prices": f"""
        select
            a.price_month, a.market_code, a.commodity_code, a.price_type, a.standard_unit,
            a.price_per_unit, a.normal_price, a.years_of_history, a.gap_from_normal,
            a.alert_level,
            {DIRECTION} as direction,
            {STRENGTH}  as strength,
            -- 1 = alert high ... 5 = alert low, 6 = not judged: used to sort and colour
            case a.alert_level
                when 'alert high' then 1 when 'watch high' then 2 when 'normal' then 3
                when 'watch low'  then 4 when 'alert low'  then 5 else 6
            end as alert_order
        from fct_price_alerts a
        order by a.price_month, a.market_code, a.commodity_code, a.price_type
    """,
    # why each price is off normal (step 4b); a separate file so the report's
    # existing tables are unchanged
    "alert_types": """
        select price_month, market_code, commodity_code, price_type, alert_type,
               markets_same_direction, markets_judged, months_running,
               general_gap, gap_after_general_shift, next_month
        from fct_alert_types
        where alert_type is not null
        order by price_month, market_code, commodity_code, price_type
    """,
    "markets": """
        select market_code, market, region, department, lat, lon, first_month, last_month,
               months_with_prices, missing_months, coverage, is_reporting_now
        from dim_markets
        order by market
    """,
    "commodities": """
        select distinct commodity_code, commodity, commodity_category
        from fct_monthly_prices
        order by commodity
    """,
    # prices far from what other markets charged that month (kept, but left out of alerts)
    "suspect": """
        select price_month, market, region, commodity, price_type, standard_unit,
               round(price_per_unit, 2) as price_per_unit, national_median, ratio_to_national
        from fct_monthly_prices
        where is_suspect_price
        order by ratio_to_national desc
    """,
    "forecast": f"""
        select forecast_month, market_code, commodity_code, price_type, last_price,
               forecast_price, forecast_low, forecast_high, normal_price, years_of_history,
               forecast_gap_from_normal, forecast_alert_level,
               {DIRECTION.replace('alert_level', 'forecast_alert_level')} as forecast_direction
        from forecast_next_month
        order by market_code, commodity_code, price_type
    """,
}

log = logging.getLogger("export_powerbi")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(WAREHOUSE), read_only=True) as con:
        for name, query in QUERIES.items():
            path = OUT_DIR / f"{name}.csv"
            # forward slashes: DuckDB's COPY wants a plain string path
            con.sql(f"copy ({query}) to '{path.as_posix()}' (header, delimiter ',')")
            rows = con.sql(f"select count(*) from read_csv('{path.as_posix()}')").fetchall()[0][0]
            log.info("%-12s %s rows", name, f"{rows:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
