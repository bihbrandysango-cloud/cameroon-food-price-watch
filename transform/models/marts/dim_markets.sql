-- One row per market: where it is and how complete its price history is.
-- "Gaps" are months between a market's first and last report with no price
-- at all. Later steps use this to decide which markets have enough history
-- to say what a "normal" price is.

with prices as (

    select * from {{ ref('stg_wfp__prices') }}

),

per_market as (

    select
        market_code,
        any_value(market)                                    as market,
        any_value(region)                                    as region,
        any_value(department)                                as department,
        any_value(lat)                                       as lat,
        any_value(lon)                                       as lon,
        min(price_month)                                     as first_month,
        max(price_month)                                     as last_month,
        count(distinct price_month)                          as months_with_prices,
        count(distinct commodity_code)                       as commodities
    from prices
    group by market_code

)

select
    *,
    date_diff('month', first_month, last_month) + 1          as months_in_span,
    months_in_span - months_with_prices                      as missing_months,
    round(months_with_prices / months_in_span, 2)            as coverage,
    last_month = (select max(price_month) from prices)       as is_reporting_now
from per_market
