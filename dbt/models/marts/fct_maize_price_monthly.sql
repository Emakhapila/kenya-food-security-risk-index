-- Retail white maize price per county per month: the forecasting dataset (DL-016).
-- One row for every county and every month in the series range, so missing
-- months are explicit NULLs rather than absent rows.

with prices as (
    select county_pcode, month, price_kes_per_kg
    from {{ ref('stg_fpma__maize_retail') }}
),

bounds as (
    select min(month) as first_month, max(month) as last_month from prices
),

grid as (
    select c.county_pcode, gs::date as month
    from (select distinct county_pcode from prices) c
    cross join bounds b
    cross join generate_series(b.first_month, b.last_month, interval '1 month') gs
),

observed as (
    select
        g.county_pcode,
        g.month,
        p.price_kes_per_kg
    from grid g
    left join prices p using (county_pcode, month)
),

-- Runs of identical consecutive observed prices (missing months skipped, as in profiling).
runs as (
    select
        county_pcode,
        month,
        row_number() over (partition by county_pcode order by month)
          - row_number() over (partition by county_pcode, price_kes_per_kg order by month) as run_id
    from observed
    where price_kes_per_kg is not null
),

run_lengths as (
    select
        county_pcode,
        month,
        count(*) over (partition by county_pcode, run_id) as run_length
    from runs
)

select
    o.county_pcode,
    d.county_name,
    o.month,
    o.price_kes_per_kg,
    ln(o.price_kes_per_kg)                                    as log_price,
    o.price_kes_per_kg is not null                            as is_observed,
    coalesce(r.run_length, 0)                                 as flat_run_length,
    coalesce(r.run_length >= {{ var('flat_run_min_months') }}, false) as is_flat_run,
    o.county_pcode in ({{ "'" ~ var('low_resolution_counties') | join("', '") ~ "'" }}) as is_low_resolution
from observed o
join {{ ref('dim_county') }} d using (county_pcode)
left join run_lengths r using (county_pcode, month)
