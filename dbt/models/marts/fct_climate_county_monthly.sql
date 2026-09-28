-- Monthly rainfall and vegetation per county (DL-017).
-- A county uses its own county-level (adm1) unit where one exists; otherwise
-- the n_pixels-weighted mean of its available sub-county (adm2) units.
-- Anomalies are ratios of aggregated values (observed / long-term average),
-- not averages of ratios. Months with fewer than 3 dekads are flagged incomplete.

with rain_unit_month as (
    select
        county_pcode, unit_pcode, adm_level, month,
        max(n_pixels)                      as n_pixels,
        sum(rain_mm)                       as rain_mm,
        sum(rain_avg_mm)                   as rain_avg_mm,
        count(*)                           as n_dekads,
        bool_or(version = 'prelim')        as has_prelim
    from {{ ref('stg_rainfall__dekadal') }}
    group by 1, 2, 3, 4
),

ndvi_unit_month as (
    select
        county_pcode, unit_pcode, adm_level, month,
        max(n_pixels)                      as n_pixels,
        avg(ndvi)                          as ndvi,
        avg(ndvi_avg)                      as ndvi_avg,
        count(*)                           as n_dekads
    from {{ ref('stg_ndvi__dekadal') }}
    group by 1, 2, 3, 4
),

county_level as (
    -- which admin level each county uses: 1 if a county-level unit exists
    select county_pcode, min(adm_level) as source_level
    from {{ ref('stg_rainfall__dekadal') }}
    group by 1
),

rain_county as (
    select
        r.county_pcode, r.month,
        sum(r.rain_mm * r.n_pixels) / sum(r.n_pixels)       as rain_mm,
        sum(r.rain_avg_mm * r.n_pixels) / sum(r.n_pixels)   as rain_avg_mm,
        min(r.n_dekads)                                      as rain_dekads,
        bool_or(r.has_prelim)                                as rain_is_provisional,
        count(*)                                             as rain_units_used
    from rain_unit_month r
    join county_level c
      on c.county_pcode = r.county_pcode and c.source_level = r.adm_level
    group by 1, 2
),

ndvi_county as (
    select
        n.county_pcode, n.month,
        sum(n.ndvi * n.n_pixels) / sum(n.n_pixels)          as ndvi,
        sum(n.ndvi_avg * n.n_pixels) / sum(n.n_pixels)      as ndvi_avg,
        min(n.n_dekads)                                      as ndvi_dekads
    from ndvi_unit_month n
    join county_level c
      on c.county_pcode = n.county_pcode and c.source_level = n.adm_level
    group by 1, 2
),

rain_3m as (
    select
        *,
        sum(rain_mm)     over w as rain_3m_mm,
        sum(rain_avg_mm) over w as rain_3m_avg_mm,
        count(*)         over w as months_in_window
    from rain_county
    window w as (partition by county_pcode order by month
                 rows between 2 preceding and current row)
)

select
    r.county_pcode,
    d.county_name,
    r.month,
    case c.source_level when 1 then 'adm1' else 'adm2_proxy' end         as climate_source_level,
    r.rain_units_used,
    round(r.rain_mm, 2)                                                   as rain_mm,
    round(r.rain_avg_mm, 2)                                               as rain_avg_mm,
    round(100 * r.rain_mm / nullif(r.rain_avg_mm, 0), 1)                  as rain_1m_anom_pct,
    case when r.months_in_window = 3
         then round(100 * r.rain_3m_mm / nullif(r.rain_3m_avg_mm, 0), 1) end as rain_3m_anom_pct,
    round(n.ndvi, 4)                                                      as ndvi,
    round(n.ndvi_avg, 4)                                                  as ndvi_avg,
    round(100 * n.ndvi / nullif(n.ndvi_avg, 0), 1)                        as ndvi_anom_pct,
    r.rain_dekads = 3                                                     as rain_month_complete,
    coalesce(n.ndvi_dekads = 3, false)                                    as ndvi_month_complete,
    r.rain_is_provisional
from rain_3m r
join county_level c using (county_pcode)
join {{ ref('dim_county') }} d using (county_pcode)
left join ndvi_county n using (county_pcode, month)
