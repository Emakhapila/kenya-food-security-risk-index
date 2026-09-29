-- One row per county and IPC analysis.
select county_pcode, analysis_month, count(*) as n
from {{ ref('fct_ipc_county_analysis') }}
group by county_pcode, analysis_month
having count(*) > 1
