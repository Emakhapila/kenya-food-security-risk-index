-- Every component and index value is a risk between 0 and 1 (DL-022).
select *
from {{ ref('fct_risk_index_monthly') }}
where not (
        coalesce(risk_rain, 0)              between 0 and 1
    and coalesce(risk_ndvi, 0)              between 0 and 1
    and coalesce(risk_price, 0)             between 0 and 1
    and coalesce(index_v2_climate, 0)       between 0 and 1
    and coalesce(index_v3_climate_price, 0) between 0 and 1
    and coalesce(risk_index, 0)             between 0 and 1
)
