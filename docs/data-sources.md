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

- To profile on Day 2.
