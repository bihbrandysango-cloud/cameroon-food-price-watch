-- Shelf 2, "clean": one row per raw price, with every price turned into a
-- price per standard unit (FCFA per kg, per litre or per piece).
--
-- WFP records the same food in many sizes: maize per kg, per 15 kg, 18 kg,
-- 90 kg and 100 kg bags. "100 KG" at 35,000 is the same as "KG" at 350, so
-- we divide by the pack size before anything gets compared.

with source as (

    select * from {{ source('raw', 'wfp_food_prices_cmr') }}

),

units as (

    select
        *,
        -- "100 KG" -> 100, "KG" -> 1, "400 G" -> 400, "20 L" -> 20, "1 piece" -> 1
        coalesce(try_cast(regexp_extract(unit, '^([0-9.]+) ', 1) as double), 1) as pack_size,
        upper(regexp_replace(unit, '^[0-9.]+ ', '')) as unit_base
    from source

)

select
    -- when and where
    reference_period_start                             as price_month,
    admin1_code                                        as region_code,
    admin1_name                                        as region,
    admin2_name                                        as department,
    market_code,
    market_name                                        as market,
    lat,
    lon,

    -- what
    commodity_code,
    commodity_name                                     as commodity,
    commodity_category,
    lower(price_type)                                  as price_type,

    -- the price as recorded
    unit                                               as unit_recorded,
    price                                              as price_recorded,

    -- the price per standard unit
    case
        when unit_base in ('KG', 'G') then 'kg'
        when unit_base = 'L'          then 'litre'
        when unit_base = 'PIECE'      then 'piece'
    end                                                as standard_unit,
    price / case
        when unit_base = 'G' then pack_size / 1000     -- grams to kg
        else pack_size
    end                                                as price_per_unit,
    currency_code                                      as currency

from units
-- Daily wages are prices of labour, not food; they are not part of this project
where commodity_category != 'non-food'
