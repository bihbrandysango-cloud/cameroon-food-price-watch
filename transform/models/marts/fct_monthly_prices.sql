-- Shelf 3, "ready": one price per market, food, price type and month, in a
-- standard unit, with a flag on prices that look far out of line.
--
-- A flagged price is kept, not deleted. It may be real (a border market,
-- a road closed by conflict) or a typing mistake, and a person should decide.

with prices as (

    select * from {{ ref('stg_wfp__prices') }}

),

national as (

    -- What most markets charged for the same food, price type and month
    select
        commodity_code,
        price_type,
        price_month,
        median(price_per_unit)        as national_median,
        count(distinct market_code)   as markets_reporting
    from prices
    group by all

)

select
    p.price_month,
    p.region_code,
    p.region,
    p.department,
    p.market_code,
    p.market,
    p.commodity_code,
    p.commodity,
    p.commodity_category,
    p.price_type,
    p.standard_unit,
    round(p.price_per_unit, 2)                                   as price_per_unit,
    p.currency,
    p.unit_recorded,
    p.price_recorded,
    n.national_median,
    n.markets_reporting,
    round(p.price_per_unit / n.national_median, 2)               as ratio_to_national,
    coalesce(
        n.markets_reporting >= {{ var('min_markets_for_median') }}
        and (
            p.price_per_unit > n.national_median * {{ var('outlier_ratio') }}
            or p.price_per_unit < n.national_median / {{ var('outlier_ratio') }}
        ),
        false
    )                                                            as is_suspect_price

from prices p
join national n using (commodity_code, price_type, price_month)
