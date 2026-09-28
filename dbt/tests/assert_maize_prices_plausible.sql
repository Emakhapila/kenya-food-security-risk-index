-- Retail maize should cost more than 0 and less than 300 KES/kg. Returns implausible rows.
select county_pcode, month, price_kes_per_kg
from {{ ref('fct_maize_price_monthly') }}
where price_kes_per_kg is not null
  and (price_kes_per_kg <= 0 or price_kes_per_kg >= 300)
