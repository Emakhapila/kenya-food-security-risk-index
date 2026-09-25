-- Each source name must map to exactly one county. Returns offending rows.
select source, raw_name, count(*) as n
from {{ ref('county_alias') }}
group by source, raw_name
having count(*) > 1
