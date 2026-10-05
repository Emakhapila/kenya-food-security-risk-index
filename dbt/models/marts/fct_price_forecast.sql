-- Current retail maize price forecast: the latest run of modelling/forecast_maize.py
-- (DL-021, DL-025). Earlier runs stay in forecasts.maize_price_forecast_runs.

with latest as (
    select max(run_at) as run_at
    from {{ source('forecasts', 'maize_price_forecast_runs') }}
)

select
    f.county_pcode,
    d.county_name,
    f.origin_month,
    f.target_month,
    f.horizon,
    f.model,
    f.last_price_kes_per_kg,
    f.forecast_kes_per_kg,
    f.lower_80_kes_per_kg,
    f.upper_80_kes_per_kg,
    round(100 * (f.forecast_kes_per_kg / f.last_price_kes_per_kg - 1), 1) as change_pct,
    f.interval_errors_n,
    f.is_low_resolution,
    f.run_at
from {{ source('forecasts', 'maize_price_forecast_runs') }} f
join latest using (run_at)
join {{ ref('dim_county') }} d using (county_pcode)
