# Data sources

## WFP Food Prices — Kenya

- **URL:** <https://data.humdata.org/dataset/wfp-food-prices-for-kenya>
- **Licence:** CC BY for Intergovernmental Organisations
- **File:** wfp_food_prices_ken.csv · 27,343 rows · 2006-01 to 2026-08 · all prices in KES
- **Grain:** market × commodity × price type × unit × month
- **Keys:** use `market_id` and `commodity_id`, not names

**Findings**

- `admin1` is the pre-2013 province; the county is in `admin2`.
- One market (Hola, Tana River) has blank admin fields; county taken from the market name via a manual override.
- Units vary within a commodity (KG, 50/64/90/126 KG bags); all maize converted to KES per kg.
- Price flags: 17,984 actual, 9,105 aggregate, 254 both. No duplicate prices at market/commodity/type/unit/date level.
- Maize is split across names that changed around 2020–2021 with different market IDs. Tested joins; none supported (see DL-014).
- Wholesale "Maize", 5 main markets (Eldoret, Kisumu, Mombasa, Nairobi, Nakuru), 2006-01 to 2022-04 is the only long dense series.
- Recent retail series: dense only in refugee camp markets (Kakuma, Kalobeyei, Dadaab: 38–53 months); town markets have at most 9 months. Markets classified by type (DL-015).
- KNBS is one of the contributing sources, so KNBS prices are not ingested separately.

## Rainfall, NDVI, IPC

- ## WFP Rainfall Indicators at Subnational Level — Kenya (HDX)

- **File:** ken-rainfall-subnat-full.csv (also a 5-year file) · stable API download link
- **Grain:** unit × dekad · 1981-01 to 2026-09 · CHIRPS-based
- **Units:** 81 (8 counties at adm1, 73 sub-counties at adm2; every county has 1–4 units) (DL-017)
- **Columns:** rfh/r1h/r3h (dekad, 1-month, 3-month rainfall mm) with long-term averages; rfq/r1q/r3q anomalies (% of 1989–2018 average)
- **Versioning:** latest dekad is `prelim`, later revised to `final`

## WFP NDVI at Subnational Level — Kenya (HDX)

- **File:** ken-ndvi-subnat-full.csv · same 81 units as rainfall
- **Grain:** unit × dekad · 2002-07 to 2026-09 · MODIS-based
- **Columns:** vim (NDVI), vim_avg (long-term average), viq (anomaly, % of average). No version column.
- **To check:** reference period for vim_avg

## IPC

## IPC Acute Food Insecurity — Kenya (HDX)

- **File:** ipc_ken_area_long.csv (full history; the `_latest` files hold only the most recent analysis)
- **Grain:** analysis × area × validity period (current / first projection) × phase (1–5, 3+, all); population numbers and rounded percentages
- **Coverage:** 12 current analyses, 2021-02 to 2026-07 (twice yearly); about 23 areas each; all 16 FEWS NET counties included
- **Issues:** inconsistent area names (case, abbreviations); sub-county splits for Marsabit and Turkana in 2024-07 only; refugee camps listed as areas; `Level 1` labels unstable
