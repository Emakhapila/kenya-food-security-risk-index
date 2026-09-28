-- One row per county and month.
select county_pcode, month, count(*) as n
from {{ ref('fct_maize_price_monthly') }}
group by county_pcode, month
having count(*) > 1
