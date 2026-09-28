-- WFP MODIS NDVI per admin unit per dekad, typed. Most recent load wins (DL-019).

with latest as (
    select distinct on (pcode, date) *
    from {{ source('raw', 'ndvi') }}
    order by pcode, date, load_id desc
)

select
    pcode                                   as unit_pcode,
    left(pcode, 5)                          as county_pcode,
    adm_level::int                          as adm_level,
    date::date                              as dekad_start,
    date_trunc('month', date::date)::date   as month,
    n_pixels::numeric                       as n_pixels,
    vim::numeric                            as ndvi,
    vim_avg::numeric                        as ndvi_avg,
    load_id
from latest
