-- "Normal" must come from earlier years only. A price in the first year a
-- market recorded a food can have no history, so it must never get an alert.
-- If this fails, the history join is peeking at the same or later years.
with first_year as (
    select market_code, commodity_code, price_type, min(year(price_month)) as first_year
    from {{ ref('fct_price_alerts') }}
    group by all
)
select a.*
from {{ ref('fct_price_alerts') }} a
join first_year f using (market_code, commodity_code, price_type)
where year(a.price_month) = f.first_year
  and (a.years_of_history > 0 or a.alert_level != 'not enough history')
