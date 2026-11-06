-- Two prices for the same market, food, price type and month would mean the
-- raw data has duplicates and every average after this would be skewed.
select market_code, commodity_code, price_type, price_month, count(*) as prices
from {{ ref('fct_monthly_prices') }}
group by all
having count(*) > 1
