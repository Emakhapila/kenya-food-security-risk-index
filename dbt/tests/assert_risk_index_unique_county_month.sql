-- One row per county and month.
select county_pcode, month, count(*) as n
from {{ ref('fct_risk_index_monthly') }}
group by county_pcode, month
having count(*) > 1
