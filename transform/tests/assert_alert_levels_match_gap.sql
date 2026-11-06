-- Every level must agree with its gap and the thresholds in dbt_project.yml.
select *
from {{ ref('fct_price_alerts') }}
where (alert_level = 'alert high' and gap_from_normal <  {{ var('alert_threshold') }})
   or (alert_level = 'alert low'  and gap_from_normal > -{{ var('alert_threshold') }})
   or (alert_level = 'normal'     and abs(gap_from_normal) >= {{ var('watch_threshold') }})
   or (alert_level != 'not enough history' and years_of_history < {{ var('min_years_history') }})
