-- This month's watch list: every price in the latest month that is outside
-- the normal range, furthest from normal first. This is what someone would
-- read first each month.

with alerts as (

    select * from {{ ref('fct_price_alerts') }}

)

select
    price_month,
    alert_level,
    region,
    market,
    commodity,
    price_type,
    standard_unit,
    round(price_per_unit) as price,
    round(normal_price)   as normal_price,
    gap_from_normal,
    years_of_history
from alerts
where price_month = (select max(price_month) from alerts)
  and alert_level not in ('normal', 'not enough history')
order by abs(gap_from_normal) desc
