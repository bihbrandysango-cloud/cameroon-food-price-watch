-- Step 4b: is a flagged price a one-off, or a real change in the market?
--
-- fct_price_alerts says a price is far from normal. This model asks why,
-- using only what was known that month:
--
--   general price shift  most foods in most markets moved the same way that
--                        month, so it looks like general inflation (or a
--                        currency move), not something about this food
--   market-wide shift    this food moved the same way in at least half of the
--                        markets that could be judged: a real change in supply
--                        or demand, such as a bad or a bumper harvest
--   local, lasting       only this market, but off for several months running
--   local, new           only this market, and the first month or so: could be
--                        a one-off blip, a local shock or a data problem
--
-- The general level is the median gap of every judged price that month. It
-- is a stand-in for the official consumer price index, which isn't in the
-- data. The next month's outcome is added only to check the labels later
-- (did a "local, new" alert go back to normal?); it never decides a label.

with alerts as (

    select
        *,
        case
            when alert_level in ('alert high', 'watch high') then 'high'
            when alert_level in ('alert low', 'watch low')   then 'low'
        end as direction
    from {{ ref('fct_price_alerts') }}
    where alert_level != 'not enough history'

),

general_level as (

    -- How far all judged prices were from normal that month, across every food
    select
        price_month,
        price_type,
        median(gap_from_normal) as general_gap,
        count(*)                as prices_judged
    from alerts
    group by all

),

breadth as (

    -- For each food and month: how many markets could be judged, and how many
    -- moved high or low
    select
        commodity_code,
        price_type,
        price_month,
        count(*)                                  as markets_judged,
        count(*) filter (where direction = 'high') as markets_high,
        count(*) filter (where direction = 'low')  as markets_low
    from alerts
    group by all

),

runs as (

    -- Months in a row this market has been off normal in the same direction
    select
        *,
        sum(case when starts_run then 1 else 0 end) over (
            partition by market_code, commodity_code, price_type
            order by price_month
        ) as run_id
    from (
        select
            *,
            direction is distinct from lag(direction) over w
              or date_diff('month', lag(price_month) over w, price_month) != 1
              or lag(price_month) over w is null as starts_run,
            lead(direction) over w                                       as next_direction,
            date_diff('month', price_month, lead(price_month) over w)    as months_to_next
        from alerts
        window w as (partition by market_code, commodity_code, price_type order by price_month)
    )

),

labelled as (

    select
        r.*,
        row_number() over (
            partition by r.market_code, r.commodity_code, r.price_type, r.run_id
            order by r.price_month
        ) as months_running,
        g.general_gap,
        g.prices_judged,
        b.markets_judged,
        case r.direction when 'high' then b.markets_high when 'low' then b.markets_low end
            as markets_same_direction
    from runs r
    join general_level g using (price_month, price_type)
    join breadth b       using (commodity_code, price_type, price_month)

)

select
    price_month,
    region,
    market_code,
    market,
    commodity_code,
    commodity,
    price_type,
    alert_level,
    direction,
    price_per_unit,
    normal_price,
    gap_from_normal,
    general_gap,
    round(gap_from_normal - general_gap, 3) as gap_after_general_shift,
    markets_judged,
    markets_same_direction,
    months_running,
    case
        when direction is null then null
        when abs(general_gap) >= {{ var('watch_threshold') }}
         and sign(general_gap) = sign(gap_from_normal)
         and abs(gap_from_normal - general_gap) < {{ var('watch_threshold') }}
            then 'general price shift'
        when markets_judged >= {{ var('min_markets_for_breadth') }}
         and markets_same_direction >= {{ var('market_wide_share') }} * markets_judged
            then 'market-wide shift'
        when months_running >= {{ var('lasting_months') }}
            then 'local, lasting'
        else 'local, new'
    end as alert_type,
    -- For checking the labels afterwards only
    case
        when direction is null or months_to_next is null or months_to_next != 1 then 'unknown'
        when next_direction = direction                                          then 'still off'
        else 'back to normal'
    end as next_month
from labelled
