-- Monthly county risk index (DL-022). Measures shocks: how unusual conditions are
-- for a county compared with its own earlier history, not chronic food insecurity.
--
-- Each component is a percentile against the county's own earlier values only
-- (macro history_percentile), oriented so that 1 = high risk:
--   rainfall   3-month total vs the same calendar window in earlier years  (1 - pct)
--   vegetation monthly NDVI vs the same calendar month in earlier years    (1 - pct)
--   price      log price minus the mean log price of the same month in the
--              3 previous years (at least 2 present), vs all earlier months (pct)
--
-- Variant columns require all of their components, so the validation compares
-- variants on identical county-months. risk_index is the published value: the
-- mean of whichever components exist, with rainfall required.

{% set min_years = var('index_min_history_years') %}
{% set min_price_months = var('index_min_price_history_months') %}

with climate as (
    select
        county_pcode,
        month,
        climate_source_level,
        case when rain_month_complete then rain_mm end    as rain_mm,
        case when ndvi_month_complete then ndvi end       as ndvi
    from {{ ref('fct_climate_county_monthly') }}
),

rain_3m as (
    -- the month and the 2 before it, all 3 present, complete and consecutive;
    -- an incomplete latest month would otherwise read as a false drought
    select
        county_pcode,
        month,
        case when lag(month, 2) over w = (month - interval '2 months')::date
              and count(rain_mm) over w3 = 3
             then sum(rain_mm) over w3 end                as rain_3m_mm
    from climate
    window w  as (partition by county_pcode order by month),
           w3 as (partition by county_pcode order by month
                  rows between 2 preceding and current row)
),

price_measure as (
    -- same-month comparison removes seasonality. At least 2 of the 3 earlier
    -- years are required, so a source-wide gap (FEWS NET published nothing in
    -- Feb-Jul 2023) does not remove those months for the following 3 years
    select
        p.county_pcode,
        p.month,
        case when num_nonnulls(p12.log_price, p24.log_price, p36.log_price) >= 2 then
            p.log_price
            - (coalesce(p12.log_price, 0) + coalesce(p24.log_price, 0) + coalesce(p36.log_price, 0))
              / num_nonnulls(p12.log_price, p24.log_price, p36.log_price)
        end                                                         as price_dev
    from {{ ref('fct_maize_price_monthly') }} p
    left join {{ ref('fct_maize_price_monthly') }} p12
      on p12.county_pcode = p.county_pcode and p12.month = (p.month - interval '12 months')::date
    left join {{ ref('fct_maize_price_monthly') }} p24
      on p24.county_pcode = p.county_pcode and p24.month = (p.month - interval '24 months')::date
    left join {{ ref('fct_maize_price_monthly') }} p36
      on p36.county_pcode = p.county_pcode and p36.month = (p.month - interval '36 months')::date
),

rain_pct  as ({{ history_percentile('rain_3m', 'rain_3m_mm', true, min_years) }}),
ndvi_pct  as ({{ history_percentile('climate', 'ndvi', true, min_years) }}),
price_pct as ({{ history_percentile('price_measure', 'price_dev', false, min_price_months) }}),

components as (
    select
        c.county_pcode,
        c.month,
        c.climate_source_level,
        r.rain_3m_mm,
        pm.price_dev,
        1 - rp.pct      as risk_rain,
        1 - np.pct      as risk_ndvi,
        pp.pct          as risk_price,
        rp.n_history    as rain_history_years,
        np.n_history    as ndvi_history_years,
        pp.n_history    as price_history_months
    from climate c
    left join rain_3m r        using (county_pcode, month)
    left join rain_pct rp      using (county_pcode, month)
    left join ndvi_pct np      using (county_pcode, month)
    left join price_measure pm using (county_pcode, month)
    left join price_pct pp     using (county_pcode, month)
)

select
    c.county_pcode,
    d.county_name,
    c.month,
    c.climate_source_level,
    round(c.rain_3m_mm, 1)                                            as rain_3m_mm,
    round(c.price_dev, 4)                                             as price_dev,
    round(c.risk_rain, 4)                                             as risk_rain,
    round(c.risk_ndvi, 4)                                             as risk_ndvi,
    round(c.risk_price, 4)                                            as risk_price,
    -- validation variants (DL-022): all components required
    round(c.risk_rain, 4)                                             as index_v1_rain,
    round((c.risk_rain + c.risk_ndvi) / 2, 4)                         as index_v2_climate,
    round((c.risk_rain + c.risk_ndvi + c.risk_price) / 3, 4)          as index_v3_climate_price,
    -- published index: mean of available components, rainfall required
    case when c.risk_rain is not null then round(
        (c.risk_rain + coalesce(c.risk_ndvi, 0) + coalesce(c.risk_price, 0))
        / (1 + (c.risk_ndvi is not null)::int + (c.risk_price is not null)::int), 4)
    end                                                               as risk_index,
    concat_ws('+',
        case when c.risk_rain  is not null then 'rain'  end,
        case when c.risk_ndvi  is not null then 'ndvi'  end,
        case when c.risk_price is not null then 'price' end)          as index_components,
    c.rain_history_years,
    c.ndvi_history_years,
    c.price_history_months
from components c
join {{ ref('dim_county') }} d using (county_pcode)
where c.risk_rain is not null
