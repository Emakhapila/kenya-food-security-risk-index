-- FEWS NET retail white maize prices (via FAO GIEWS FPMA), one row per county and month.
-- Raw keeps every version of every value (DL-019); here the most recent load wins.

with latest as (
    select distinct on (series, date)
        load_id,
        export_file,
        series,
        date,
        price
    from {{ source('raw', 'fpma') }}
    order by series, date, load_id desc
),

parsed as (
    select
        trim(split_part(series, ',', 3))                         as county_raw,
        to_date(date, 'MM/DD/YYYY')                              as month,
        nullif(trim(price), '')::numeric                         as price_kes_per_kg,
        trim(split_part(series, ',', 4))                         as commodity,
        trim(split_part(series, ',', 2))                         as price_type,
        trim(split_part(series, ',', 5))                         as unit,
        to_date(substring(export_file from '(\d{4}-\d{2}-\d{2})'), 'YYYY-MM-DD') as export_date,
        load_id
    from latest
)

select
    a.county_pcode,
    p.county_raw,
    p.month,
    p.price_kes_per_kg,
    p.commodity,
    p.price_type,
    p.unit,
    p.export_date,
    p.load_id
from parsed p
left join {{ ref('county_alias') }} a
    on a.source = 'fpma'
   and a.raw_name = p.county_raw
