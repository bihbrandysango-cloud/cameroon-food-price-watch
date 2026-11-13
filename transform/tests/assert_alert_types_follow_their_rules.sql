-- Every alert type must meet its own rule, and normal prices get no type.
-- Returns the rows that break a rule; the check passes when it returns none.

select *
from {{ ref('fct_alert_types') }}
where (direction is null and alert_type is not null)
   or (direction is not null and alert_type is null)
   or (alert_type = 'market-wide shift'
       and (markets_judged < {{ var('min_markets_for_breadth') }}
            or markets_same_direction < {{ var('market_wide_share') }} * markets_judged))
   or (alert_type = 'local, lasting' and months_running < {{ var('lasting_months') }})
