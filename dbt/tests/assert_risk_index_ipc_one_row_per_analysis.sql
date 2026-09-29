-- Exactly one validation row for every county-analysis in the IPC target.
with a as (select count(*) as n from {{ ref('fct_ipc_county_analysis') }}),
     b as (select count(*) as n,
                  count(distinct (county_pcode, analysis_month)) as n_distinct
           from {{ ref('fct_risk_index_ipc') }})
select a.n as ipc_rows, b.n as validation_rows, b.n_distinct
from a, b
where a.n <> b.n or b.n <> b.n_distinct
