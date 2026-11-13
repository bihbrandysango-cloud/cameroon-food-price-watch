-- This month's watch list: every price in the latest month that is outside
-- the normal range, furthest from normal first. This is what someone would
-- read first each month.

with alerts as (

    select
        a.*,
        t.alert_type,
        t.markets_same_direction,
        t.markets_judged,
        t.months_running
    from {{ ref('fct_price_alerts') }} a
    left join {{ ref('fct_alert_types') }} t
      using (market_code, commodity_code, price_type, price_month)

)

select
    price_month,
    alert_level,
    alert_type,
    region,
    market,
    commodity,
    price_type,
    standard_unit,
    round(price_per_unit) as price,
    round(normal_price)   as normal_price,
    gap_from_normal,
    years_of_history,
    markets_same_direction || ' of ' || markets_judged as markets_moving_same_way,
    months_running
from alerts
where price_month = (select max(price_month) from alerts)
  and alert_level not in ('normal', 'not enough history')
order by abs(gap_from_normal) desc
