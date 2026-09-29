-- IPC's published "3+" figure should equal Phase 3 + 4 + 5 (allowing for
-- rounding to the nearest 1,000). Warn only: the mart uses the published 3+.
{{ config(severity = 'warn') }}

with a as (
    select analysis_month, area_raw,
           max(population) filter (where phase = '3+')             as p3plus,
           sum(population) filter (where phase in ('3', '4', '5')) as p3to5
    from {{ ref('stg_ipc__area_phase') }}
    where validity_period = 'current'
    group by 1, 2
)
select *
from a
where abs(p3plus - p3to5) > 1000
