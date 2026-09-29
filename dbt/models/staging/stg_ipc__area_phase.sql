-- IPC acute food insecurity, one row per analysis, area, validity period and phase (DL-018).
-- Raw keeps every version (DL-019); here the most recent load wins.
-- All rows are kept, including projections and excluded areas (refugee camps);
-- filtering happens in fct_ipc_county_analysis so the choices stay visible.

with latest as (
    select distinct on (date_of_analysis, area, validity_period, phase)
        load_id,
        date_of_analysis,
        trim(area)        as area,
        validity_period,
        "from",
        "to",
        phase,
        number,
        percentage
    from {{ source('raw', 'ipc') }}
    order by date_of_analysis, area, validity_period, phase, load_id desc
)

select
    to_date(l.date_of_analysis, 'Mon YYYY')                       as analysis_month,
    l.area                                                        as area_raw,
    a.county_pcode,
    coalesce(a.include, false)                                    as is_included,
    coalesce(a.match_method = 'rule', false)                      as is_subcounty_area,
    l.validity_period,
    nullif(l."from", '')::date                                    as valid_from,
    nullif(l."to", '')::date                                      as valid_to,
    l.phase,
    replace(nullif(trim(l.number), ''), ',', '')::numeric         as population,
    nullif(trim(l.percentage), '')::numeric                       as percentage_rounded,
    l.load_id
from latest l
left join {{ ref('county_alias') }} a
    on a.source = 'ipc'
   and a.raw_name = l.area
