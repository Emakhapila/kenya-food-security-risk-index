-- One row per county and month in the climate table.
select county_pcode, month, count(*) as n
from {{ ref('fct_climate_county_monthly') }}
group by county_pcode, month
having count(*) > 1
