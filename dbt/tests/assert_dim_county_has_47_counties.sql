-- Kenya has 47 counties. Returns a row if the dimension has any other number.
select count(*) as n_counties
from {{ ref('dim_county') }}
having count(*) <> 47
