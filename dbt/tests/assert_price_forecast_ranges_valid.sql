-- Each forecast sits inside its 80% range, prices are positive, and there is one
-- row per county and horizon.
select county_pcode, horizon, count(*) over (partition by county_pcode, horizon) as n,
       lower_80_kes_per_kg, forecast_kes_per_kg, upper_80_kes_per_kg
from {{ ref('fct_price_forecast') }}
where not (0 < lower_80_kes_per_kg
           and lower_80_kes_per_kg <= forecast_kes_per_kg
           and forecast_kes_per_kg <= upper_80_kes_per_kg)
   or county_pcode in (
        select county_pcode from {{ ref('fct_price_forecast') }}
        group by county_pcode, horizon having count(*) > 1)
