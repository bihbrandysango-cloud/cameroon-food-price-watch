-- A price of zero or below is never real.
select *
from {{ ref('fct_monthly_prices') }}
where price_per_unit <= 0
