-- Step 4: is this price far from normal for this month in this market?
--
-- Prices rise and fall with the seasons every year (maize in Maroua is
-- usually dearest in August, before the harvest), so each price is compared
-- with the same calendar month in recent earlier years, never with later ones.
-- "Normal" is the median of those earlier prices, so one extreme year can't
-- drag it. Alerts go both ways: too high hurts buyers, too low hurts farmers.
--
-- Suspect prices from fct_monthly_prices are left out: a typing mistake
-- shouldn't raise an alarm or distort what "normal" means.

with prices as (

    select
        *,
        year(price_month)  as price_year,
        month(price_month) as calendar_month
    from {{ ref('fct_monthly_prices') }}
    where not is_suspect_price

),

history as (

    -- For every price, the same market, food, price type and calendar month
    -- in the last few earlier years
    select
        cur.market_code,
        cur.commodity_code,
        cur.price_type,
        cur.price_month,
        median(past.price_per_unit) as normal_price,
        count(*)                    as years_of_history
    from prices cur
    join prices past
      on  past.market_code    = cur.market_code
      and past.commodity_code = cur.commodity_code
      and past.price_type     = cur.price_type
      and past.calendar_month = cur.calendar_month
      and past.price_year     < cur.price_year
      and past.price_year     >= cur.price_year - {{ var('history_window_years') }}
    group by all

),

compared as (

    select
        p.price_month,
        p.region,
        p.department,
        p.market_code,
        p.market,
        p.commodity_code,
        p.commodity,
        p.commodity_category,
        p.price_type,
        p.standard_unit,
        p.price_per_unit,
        h.normal_price,
        coalesce(h.years_of_history, 0)                                    as years_of_history,
        round((p.price_per_unit - h.normal_price) / h.normal_price, 3)     as gap_from_normal
    from prices p
    left join history h using (market_code, commodity_code, price_type, price_month)

)

select
    *,
    case
        when years_of_history < {{ var('min_years_history') }}  then 'not enough history'
        when gap_from_normal >=  {{ var('alert_threshold') }}   then 'alert high'
        when gap_from_normal <= -{{ var('alert_threshold') }}   then 'alert low'
        when gap_from_normal >=  {{ var('watch_threshold') }}   then 'watch high'
        when gap_from_normal <= -{{ var('watch_threshold') }}   then 'watch low'
        else 'normal'
    end as alert_level
from compared
