-- Risk index aligned to each IPC analysis, for validation (DL-022).
-- One row per county-analysis in fct_ipc_county_analysis.
--
-- Primary alignment: mean over the 3 months BEFORE the analysis month (t-3 to t-1),
-- at least 2 of 3 months required. Everything in that window was available before
-- IPC published, so it is an early-warning test.
-- Sensitivity only: the analysis month itself, and the mean over the validity window
-- (valid_from to valid_to), which includes months after publication.

{% set variants = ['index_v1_rain', 'index_v2_climate', 'index_v3_climate_price'] %}

with ipc as (
    select * from {{ ref('fct_ipc_county_analysis') }}
),

idx as (
    select * from {{ ref('fct_risk_index_monthly') }}
),

pre3 as (
    select
        i.county_pcode,
        i.analysis_month,
        {% for v in variants %}
        case when count(x.{{ v }}) >= 2 then avg(x.{{ v }}) end   as {{ v }}_pre3,
        count(x.{{ v }})                                           as {{ v }}_pre3_months,
        {% endfor %}
        max(x.climate_source_level)                                as climate_source_level
    from ipc i
    left join idx x
      on  x.county_pcode = i.county_pcode
      and x.month >= (i.analysis_month - interval '3 months')::date
      and x.month <  i.analysis_month
    group by 1, 2
),

at_month as (
    select
        i.county_pcode,
        i.analysis_month,
        {% for v in variants %}
        x.{{ v }}                                                  as {{ v }}_at_analysis{{ "," if not loop.last }}
        {% endfor %}
    from ipc i
    left join idx x
      on x.county_pcode = i.county_pcode and x.month = i.analysis_month
),

validity as (
    select
        i.county_pcode,
        i.analysis_month,
        {% for v in variants %}
        avg(x.{{ v }})                                             as {{ v }}_validity{{ "," if not loop.last }}
        {% endfor %}
    from ipc i
    left join idx x
      on  x.county_pcode = i.county_pcode
      and x.month >= date_trunc('month', i.valid_from)::date
      and x.month <= i.valid_to
    group by 1, 2
)

select
    i.county_pcode,
    i.county_name,
    i.analysis_month,
    i.share_phase3plus,
    i.is_partial_county,
    i.ipc_area_level,
    p.climate_source_level,
    {% for v in variants %}
    round(p.{{ v }}_pre3, 4)          as {{ v }}_pre3,
    p.{{ v }}_pre3_months,
    a.{{ v }}_at_analysis,
    round(w.{{ v }}_validity, 4)      as {{ v }}_validity{{ "," if not loop.last }}
    {% endfor %}
from ipc i
left join pre3 p     using (county_pcode, analysis_month)
left join at_month a using (county_pcode, analysis_month)
left join validity w using (county_pcode, analysis_month)
