-- If unit conversion works, a market's wholesale price per kg (from bags)
-- should be in the same range as its retail price per kg in the same month.
-- Fails if wholesale is more than 5x retail, a sign a bag price was not divided.
select w.market, w.commodity, w.price_month,
       w.price_per_unit as wholesale_per_kg, r.price_per_unit as retail_per_kg
from {{ ref('fct_monthly_prices') }} w
join {{ ref('fct_monthly_prices') }} r
  using (market_code, commodity_code, price_month)
where w.price_type = 'wholesale'
  and r.price_type = 'retail'
  and w.standard_unit = 'kg'
  and w.price_per_unit > r.price_per_unit * 5
