-- At most one county-level IPC area per county per analysis (DL-018).
-- Two would be summed and double-count the population, e.g. if an analysis
-- listed both "Tana River" and "TANA RIVER", or "Tharaka" and "Tharaka Nithi".
-- If this fails, decide which area to keep and record it in the decision log.
select analysis_month, county_pcode,
       string_agg(distinct area_raw, '; ') as areas
from {{ ref('stg_ipc__area_phase') }}
where validity_period = 'current'
  and is_included
  and not is_subcounty_area
group by analysis_month, county_pcode
having count(distinct area_raw) > 1
