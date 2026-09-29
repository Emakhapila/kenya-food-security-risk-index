-- IPC validation target: share of population in Phase 3+ per county per analysis (DL-018).
-- Current-period rows only (projections are IPC's own forecasts). Refugee areas are
-- excluded through county_alias.include. The share is computed from population
-- numbers, not the rounded percentage column.
-- Sub-county areas are summed to county level. If an analysis has a county-level
-- row for a county, that row is used and its sub-county rows are ignored.
-- ipc_coverage_ratio compares IPC's population with the 2019 census; areas that
-- cover only part of their county are flagged and should be validated separately.

with area_totals as (
    select
        analysis_month,
        county_pcode,
        area_raw,
        is_subcounty_area,
        min(valid_from)                                          as valid_from,
        max(valid_to)                                            as valid_to,
        max(population) filter (where phase = 'all')             as pop_total,
        max(population) filter (where phase = '3+')              as pop_phase3plus,
        sum(population) filter (where phase in ('3', '4', '5'))  as pop_phase3to5
    from {{ ref('stg_ipc__area_phase') }}
    where validity_period = 'current'
      and is_included
    group by 1, 2, 3, 4
),

county_level as (
    -- does this analysis have a county-level row for the county?
    select
        analysis_month,
        county_pcode,
        bool_or(not is_subcounty_area) as has_county_row
    from area_totals
    group by 1, 2
),

county as (
    select
        a.analysis_month,
        a.county_pcode,
        case when c.has_county_row then 'county' else 'subcounty_sum' end  as ipc_area_level,
        count(*)                                                          as ipc_areas_used,
        string_agg(a.area_raw, '; ' order by a.area_raw)                  as ipc_areas,
        min(a.valid_from)                                                 as valid_from,
        max(a.valid_to)                                                   as valid_to,
        sum(a.pop_total)                                                  as pop_total,
        -- use the published 3+ figure; fall back to phases 3-5 if it is missing
        sum(coalesce(a.pop_phase3plus, a.pop_phase3to5))                  as pop_phase3plus
    from area_totals a
    join county_level c using (analysis_month, county_pcode)
    where a.is_subcounty_area = not c.has_county_row
    group by 1, 2, 3
)

select
    c.county_pcode,
    d.county_name,
    c.analysis_month,
    c.valid_from,
    c.valid_to,
    c.ipc_area_level,
    c.ipc_areas_used,
    c.ipc_areas,
    c.pop_total,
    c.pop_phase3plus,
    round(c.pop_phase3plus / nullif(c.pop_total, 0), 4)                     as share_phase3plus,
    round(c.pop_total / nullif(d.population_2019, 0), 2)                    as ipc_coverage_ratio,
    c.pop_total / nullif(d.population_2019, 0)
        < {{ var('ipc_partial_coverage_max') }}                             as is_partial_county
from county c
join {{ ref('dim_county') }} d using (county_pcode)
