-- WFP CHIRPS rainfall per admin unit per dekad (10-day period), typed.
-- Raw keeps every version (DL-019); the most recent load wins, so a dekad
-- first published as 'prelim' is replaced by its 'final' value when revised.

with latest as (
    select distinct on (pcode, date) *
    from {{ source('raw', 'rainfall') }}
    order by pcode, date, load_id desc
)

select
    pcode                                   as unit_pcode,
    left(pcode, 5)                          as county_pcode,
    adm_level::int                          as adm_level,
    date::date                              as dekad_start,
    date_trunc('month', date::date)::date   as month,
    n_pixels::numeric                       as n_pixels,
    rfh::numeric                            as rain_mm,
    rfh_avg::numeric                        as rain_avg_mm,
    version,
    load_id
from latest
