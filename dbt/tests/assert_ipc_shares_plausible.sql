-- Phase 3+ population cannot exceed the analysed population, and every
-- county must have a positive analysed population.
select county_pcode, analysis_month, pop_total, pop_phase3plus, share_phase3plus
from {{ ref('fct_ipc_county_analysis') }}
where pop_total <= 0
   or pop_phase3plus < 0
   or pop_phase3plus > pop_total
