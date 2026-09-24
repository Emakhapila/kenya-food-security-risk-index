# Decision Log — Kenya Food Security Risk Index

This log records the significant design decisions in this project: what was decided, why, what else was considered, and when to revisit. Entries are never deleted. If a decision changes, the old entry is marked **Superseded** and linked to the new one.

**Statuses:** `Proposed` · `Accepted` · `Open` (needs a decision; blocking noted) · `Superseded by DL-XXX`

---

## Index

| ID | Decision | Status | Date |
|--- |---|--- |---|
| DL-001 | Composite risk index + price forecast, not an IPC classifier | Accepted | 2026-09-23 |
| DL-002 | Pre-aggregated subnational climate indicators, not raw rasters | Accepted | 2026-09-23 |
| DL-003 | Hosted PostgreSQL, not local Docker | Accepted (provider open) | 2026-09-23 |
| DL-004 | Layered warehouse (raw → staging → marts) with dbt | Accepted | 2026-09-23 |
| DL-005 | Append-only raw layer with load IDs and source hashes | Accepted | 2026-09-23 |
| DL-006 | Canonical county dimension built before any joins | Accepted | 2026-09-23 |
| DL-007 | Anomaly baselines computed from training-window data only | Accepted (method open) | 2026-09-23 |
| DL-008 | Exogenous rainfall input for forecasts | Open | 2026-09-23 |
| DL-009 | v1 forecast scope: maize, high-coverage markets only | Accepted (threshold open) | 2026-09-23 |
| DL-010 | Rolling-origin backtest against a seasonal-naive baseline | Accepted | 2026-09-23 |
| DL-011 | GitHub Actions for scheduling, not Airflow | Accepted | 2026-09-23 |
| DL-012 | Streamlit for the public dashboard, not Power BI | Accepted | 2026-09-23 |
| DL-013 | AWS as documented target architecture, not deployed in v1 | Accepted | 2026-09-23 |
| DL-014 | Maize price series: no cross-name joining; forecast on wholesale 2006–2022 | Accepted (live-forecast source open) | 2026-09-23 |
| DL-015 | Market type classification; index uses town markets only | Accepted | 2026-09-23 |
| DL-016 | FEWS NET retail maize (via FAO FPMA) as primary price source | Accepted | 2026-09-24 |
| DL-017 | County rainfall and NDVI estimated from available units (pixel-weighted) | Accepted | 2026-09-24 |

---

## DL-001 — Composite risk index + price forecast, not an IPC classifier

**Date:** 2026-09-23 · **Status:** Accepted

**Context.** IPC phase classifications are the obvious label for food insecurity, but for Kenya they cover only the ~23 ASAL counties and are published roughly twice a year. That gives a few hundred labelled county-periods at most, which is too few to train and honestly evaluate a classifier.

**Decision.** Build two components:

1. A monthly county-level composite risk index from price, rainfall and vegetation anomalies, **validated** against IPC phases rather than trained on them.
2. A 1–3 month maize price forecast (SARIMAX) for markets with dense price histories.

**Alternatives considered.**

- IPC phase classifier: rejected because the sample is too small, the labels are coarse, and there is heavy class imbalance.
- Index only: rejected because it has no forward-looking component and shows no forecasting rigour.
- Forecast only: rejected because it doesn't answer the county-level risk question.

**Consequences.** Validation against IPC only covers ASAL counties, so the index is unvalidated for the other 24. This must be stated as a limitation.

**Revisit if.** A denser label becomes available (e.g. monthly county-level NDMA phases in structured form).

---

## DL-002 — Pre-aggregated subnational climate indicators, not raw rasters

**Date:** 2026-09-23 · **Status:** Accepted

**Context.** Rainfall (CHIRPS) and vegetation (NDVI) are natively raster data. Aggregating them to counties requires zonal statistics, which depend on GDAL. On the development machine (Windows, no admin rights), GDAL has a history of DLL and path problems.

**Decision.** Use WFP's subnational rainfall and NDVI indicators (published on HDX, already aggregated to administrative units).

**Alternatives considered.**

- Raw CHIRPS rasters + `rasterstats`: rejected for environment risk and time cost.
- Google Earth Engine: rejected because it adds an account dependency and a second compute environment.

**Consequences.** Aggregation method and boundaries are fixed by the publisher and are not controllable. Admin codes must be mapped to the canonical county dimension (DL-006).

**Revisit if.** Finer spatial resolution (sub-county) is needed, or the published indicators stop updating.

---

## DL-003 — Hosted PostgreSQL, not local Docker

**Date:** 2026-09-23 · **Status:** Accepted (provider open)

**Context.** The development machine has no admin rights, so Docker Desktop cannot be installed. The scheduled pipeline (GitHub Actions) and the public dashboard also need a shared, always-available database.

**Decision.** Use a free-tier hosted PostgreSQL instance.

**Provider: Neon** (free plan, AWS US East 2, PostgreSQL 18). Chosen over Supabase because:

- It is plain PostgreSQL with no extra platform, which suits a dbt warehouse.
- Idle compute suspends and resumes automatically on connection; the project itself is not paused for inactivity, so the monthly pipeline and the public dashboard keep working.
- Branching allows disposable copies of the database for testing transformations.

Connections use the direct (non-pooled) string for dbt and scripts; the dashboard may move to the pooled string later.

**Alternatives considered.**

- Local Docker Postgres: blocked by permissions.
- DuckDB file in the repo: rejected because it is portable but doesn't demonstrate client–server database work, and Postgres is what ETL clients typically run.
- Cloud warehouse (BigQuery/Snowflake): rejected as unnecessary at this data volume and adding cost risk.

**Consequences.** There is a dependency on free-tier limits and availability. Credentials must be handled via GitHub Secrets and environment variables and never committed.
The first connection after an idle period takes a few seconds while compute resumes.

**Revisit if.** Free-tier limits are hit, or when the AWS deployment (DL-013) is built.

---

## DL-004 — Layered warehouse with dbt

**Date:** 2026-09-23 · **Status:** Accepted

**Context.** Three sources with different grains, naming and update cadences must be combined into county-month analytical tables.

**Decision.** Use three schemas:

- `raw`: data exactly as received.
- `staging`: typed, deduplicated, conformed to the county dimension.
- `marts`: analysis-ready facts (`fct_price_monthly`, `fct_rainfall_monthly`, `fct_risk_index`, `fct_price_forecast`).

Transformations run in dbt, with schema tests on keys, accepted values and plausible ranges.

**Alternatives considered.** Transformations in pandas scripts: rejected because they are harder to test, have no lineage, and give a weaker analytics engineering signal.

**Consequences.** Adds a dbt dependency and a learning cost, but lineage, tests and documentation come built in.

---

## DL-005 — Append-only raw layer with load IDs and source hashes

**Date:** 2026-09-23 · **Status:** Accepted

**Context.** Sources revise historical values without notice. Pipeline reruns must be safe, and it should be possible to reconstruct what the index showed at any past run.

**Decision.** Raw tables are append-only. Every load records `load_id`, `loaded_at`, `source_url` and a content hash. A load whose hash matches the previous one is skipped. Staging selects the latest load per natural key.

**Alternatives considered.** Truncate-and-reload: rejected because it destroys history and makes silent source revisions invisible.

**Consequences.** Raw storage grows over time (negligible at this volume). Revisions become detectable and reportable.

---

## DL-006 — Canonical county dimension built first

**Date:** 2026-09-23 · **Status:** Accepted

**Context.** Sources spell county names inconsistently (e.g. "Tharaka-Nithi" / "Tharaka Nithi", "Elgeyo-Marakwet" variants) and use different code systems. Unresolved mismatches fail silently as dropped rows in joins.

**Decision.** Build `dim_county` (47 counties, official code, canonical name, ASAL flag) plus a `county_alias` mapping table **before** any source is staged. A dbt test fails the build if any staged row has an unmapped county.

**Consequences.** One to two hours of upfront work, in exchange for joins that fail loudly instead of silently.

---

## DL-007 — Anomaly baselines from training-window data only

**Date:** 2026-09-23 · **Status:** Accepted (method open)

**Context.** Anomalies are computed against a "normal" baseline. If that baseline includes data from after the point being evaluated, the index and the backtests leak future information.

**Decision.** Baselines for any evaluated period use only data available before that period.

**Open:** choose the baseline method by **end of Day 7**: an expanding window or a fixed reference period (e.g. 2010–2019 climatology for rainfall), and the method for the price seasonal norm.

**Consequences.** Early periods have less stable baselines. The evaluation start date may need to move later.

---

## DL-008 — Exogenous rainfall input for forecasts

**Date:** 2026-09-23 · **Status:** Open (must be decided before Day 10)

**Context.** SARIMAX with rainfall as an exogenous variable needs rainfall values for the forecast horizon. Future observed rainfall won't exist at forecast time, so using it in a backtest overstates accuracy.

**Options.**

- (a) Lagged observed rainfall only (e.g. t−1 to t−3). Honest, and simple to implement.
- (b) Seasonal outlooks (e.g. ICPAC forecasts). More realistic, but adds another data source.
- (c) Scenario inputs (normal / dry / wet). Useful for the dashboard, but not a true forecast.

**Leaning:** (a) for v1, with (c) as an optional dashboard feature.

---

## DL-009 — v1 forecast scope: maize, high-coverage markets only

**Date:** 2026-09-23 · **Status:** Accepted (threshold open)

**Context.** WFP price coverage is uneven across markets and commodities. Forecasting sparse series produces unreliable results and inflates build time.

**Decision.** For v1, forecast maize only, in markets meeting a minimum coverage threshold (expected to be about 8–12 markets). Other commodities are v2 scope.

**Open:** set the coverage threshold after the Day 1–3 coverage profiling, and record which markets were excluded.

**Consequences.** Excluded markets may be disproportionately remote and food-insecure, so the forecast sample is biased toward better-served markets. This must be stated as a limitation.

Refined by DL-014: forecast scope is now wholesale maize in five main markets.

---

## DL-010 — Rolling-origin backtest against a seasonal-naive baseline

**Date:** 2026-09-23 · **Status:** Accepted

**Context.** A single train/test split on a short monthly series gives one noisy estimate of accuracy, and a model score means little without something to compare it to.

**Decision.** Evaluate forecasts with a rolling-origin backtest at 1-, 2- and 3-month horizons. Report MAE and MAPE per market and horizon against a seasonal-naive baseline. The index gets the same treatment: compare its agreement with IPC against a rainfall-anomaly-only alternative.

**Consequences.** More compute and more code than a single split. Results can show that SARIMAX doesn't beat the baseline for some markets or horizons, and that must be reported, not hidden.

---

## DL-011 — GitHub Actions for scheduling, not Airflow

**Date:** 2026-09-23 · **Status:** Accepted

**Context.** The sources update monthly. There is one pipeline with a linear set of steps.

**Decision.** GitHub Actions runs CI on pull requests (lint, pytest, `dbt test`) and a monthly cron job for the full pipeline.

**Alternatives considered.** Airflow or Prefect: rejected because they add hosting and operational overhead with no benefit for one monthly linear job.

**Revisit if.** The pipeline gains branching dependencies, multiple schedules, or needs backfill tooling.

---

## DL-012 — Streamlit for the public dashboard, not Power BI

**Date:** 2026-09-23 · **Status:** Accepted

**Context.** Reviewers need to open the dashboard from a GitHub link with no install or login.

**Decision.** A deliberately thin Streamlit app (one county risk view, one forecast view) on Streamlit Community Cloud.

**Alternatives considered.** Power BI: a stronger existing skill, but `.pbix` files can't be viewed from GitHub, and Publish-to-web has licensing and data-exposure constraints.

**Consequences.** Less visual polish than Power BI. The dashboard is a window into the marts, not the product.

---

## DL-013 — AWS as documented target architecture, not deployed in v1

**Date:** 2026-09-23 · **Status:** Accepted

**Context.** An AWS deployment would demonstrate cloud skills but adds build hours, cost risk, and scope creep before v1 ships.

**Decision.** v1 includes a written production target architecture (S3 raw zone, RDS PostgreSQL, Lambda or ECS for the API, EventBridge scheduling) with estimated monthly cost. The actual deployment is v2, aligned with SAA-C03 study.

**Revisit if.** v1 ships on schedule. Set up a billing alarm before creating any resources.

---

## DL-014 — Maize price series: no cross-name joining; forecast on wholesale 2006–2022

**Date:** 2026-09-23 · **Status:** Accepted (live-forecast source open)

**Context.** WFP's Kenya file splits maize across several commodity names that changed around 2020–2021, with different market IDs, units (KG vs 90 KG bags) and coverage. Profiling tested whether they could be joined into continuous series:

- Wholesale "Maize (white)" (90 KG) vs "Maize" (KG), 2006–2020, same five markets: 686 overlapping town-months, median absolute difference 4.1% (90th percentile 15.2%). Parallel series, probably from different sources.
- Wholesale "Maize" vs "Maize (white, dry)", 2021–2022: 29 overlapping town-months, median difference 12.9%, with the direction of the gap differing between markets (higher in Eldoret, lower in Mombasa). No stable offset, so no defensible level adjustment.
- Retail "Maize (white)" (to 2020) vs "Maize" (from 2020): no shared market IDs; four ASAL towns match by name (Garissa, Lodwar, Marigat, Marsabit) but have zero overlapping months and only 2–9 months of data on the new side.

**Decision.**

- Do not join series across commodity names. Each name is staged as a separate series.
- Forecasting uses wholesale "Maize" (per kg) in Eldoret, Kisumu, Mombasa, Nairobi and Nakuru, 2006-01 to 2022-04, as a historical rolling-origin backtest. "Maize (white)" 90 KG ÷ 90 may fill gaps, with filled months flagged.
- All prices are converted to KES per kg in staging.

**Alternatives considered.**

- Joining with a level adjustment: rejected because the offset is not stable across markets.
- Forecasting on retail "Maize" 2020–2026: rejected because town markets have at most 9 months of data; only refugee camp markets are dense (38–53 months), and those are excluded by DL-015.

**Consequences.** There is no live monthly price forecast from WFP data alone. The current risk signal relies more on rainfall and NDVI.

**Revisit if.** FAO GIEWS FPMA (or another source) provides a consistent wholesale series for the same five markets after April 2022.

---

## DL-015 — Market type classification; index uses town markets only

**Date:** 2026-09-23 · **Status:** Accepted

**Context.** Recent retail series include refugee camp markets and Nairobi and Mombasa informal settlements. Camp prices are driven by aid distributions; informal-settlement prices reflect urban food access. Neither reflects county-level agricultural or drought conditions. Profiling also showed that the only dense recent retail series are camp markets.

**Decision.** Add `market_type` (town / urban_informal / camp) to staging via a dbt seed. The county risk index uses `town` markets only. Other types are kept in the warehouse for later analysis.

**Classification (from profiling):**

- **camp:** IFO, Hagadera, Dagahaley (Dadaab); Kakuma 2, 3, 4; Kalobeyei Villages 1–3; Ethiopia, HongKong, Mogadishu (areas within Kakuma)
- **urban_informal:** Kangemi, Kibra, Dandora, Mathare, Kawangware, Mukuru (Nairobi); Kalahari, Junda, Bangladesh, Kisumu Ndogo, Shonda, Moroto (Mombasa)
- **town:** Lodwar, Garissa, Wajir, Marigat, Isiolo, Marsabit, Nairobi

**Consequences.** Fewer price observations for Turkana, Garissa and Nairobi. The classification is manual and must be updated when new markets appear in the data.

---

## DL-016 — FEWS NET retail maize (via FAO FPMA) as primary price source

**Date:** 2026-09-24 · **Status:** Accepted

**Context.** WFP data cannot support a current monthly price signal (DL-014). The FAO GIEWS FPMA tool carries retail white maize prices collected by FEWS NET for 16 counties, mostly ASAL (Embu-Mbeere, Garissa, Isiolo, Kilifi, Kitui, Kwale, Lamu, Makueni, Mandera, Marsabit, Meru, Taita Taveta, Tana River, Tharaka Nithi, Turkana, Wajir), 2010-01 to 2026-07, KES per kg.

Profiling:

- Coverage 95–97% per county (190–193 of 199 months).
- Two source-wide gaps: 2023-02 to 2023-07 (all counties) and 2020-05 to 2020-07 (13 counties; Garissa, Kitui and Kwale reported).
- Garissa is a coarse, step-like series: seven flat runs of 6–11 months at round 5-shilling values, including an unchanged value through the 2020 gap.
- Makueni, Taita Taveta and Wajir have isolated flat runs of 6–9 months (2013–2021).

**Decision.**

- FEWS NET retail maize via FPMA is the primary price source for the county risk index and the live monthly SARIMAX forecast.
- Missing months stay missing (SARIMAX handles them); no imputation in staging.
- Staging adds `is_flat_run` for runs of 6 or more identical months. Values are not altered.
- Garissa is included in the index but reported separately in forecast evaluation as a low-resolution series.
- "Embu-Mbeere" maps to Embu County in the alias table.

**Constraints.**

- No API: refreshed by a manual monthly CSV export (wide format, month-first dates), documented as a runbook step. The file name records the export date.
- Licence CC BY-NC-SA: raw data is not committed; derived data shared under the same terms; not suitable as-is for commercial client work.

**Alternatives considered.** WFP wholesale 2006–2022 for forecasting: kept as an optional v2 long-history backtest.

**Revisit if.** FEWS NET's own data portal offers automated access or different licence terms.

---

## DL-017 — County rainfall and NDVI estimated from available units (pixel-weighted)

**Date:** 2026-09-24 · **Status:** Accepted

**Context.** The WFP subnational rainfall file (the only files on HDX are full history and five-year subset; same units) covers 81 units: 8 counties at admin level 1 (KE004, KE008, KE010, KE019, KE023, KE037, KE043, KE047) and 73 sub-counties at admin level 2, with every county represented by 1–4 sub-counties. Direct county-level rainfall is unavailable for 39 counties, and sub-county coverage is too partial to sum into true county totals. All 16 counties with FEWS NET prices (DL-016) have at least one unit.
The WFP subnational NDVI file covers exactly the same 81 units (confirmed by PCODE comparison)

**Decision.**

- Where a county-level (admin 1) row exists, use it.
- Otherwise, estimate county rainfall as the mean of that county's available sub-county units, weighted by `n_pixels`.
- Anomalies use the source's own long-term averages (1989–2018 reference period), aggregated the same way.
- Staging records `rain_source_level` (adm1 / adm2_proxy) and `rain_units_used` per county, so coverage is visible in every downstream table.

**Alternatives considered.**

- Raster processing of CHIRPS: rejected under DL-002 (GDAL constraints on the development machine).
- SERVIR ClimateSERV area aggregation: possible without local GDAL; kept for v2 if validation shows the proxy is weak.

**Consequences.** County rainfall for 39 counties is an approximation based on part of the county's area. Large counties with diverse rainfall patterns (e.g. Garissa, Kitui) are most affected.

**Revisit if.** Index validation against IPC is noticeably weaker for proxy counties than for admin-1 counties.

---

## Known limitations (running list)

Add a line here whenever a limitation is discovered. This list feeds the README's limitations section.

- Index validation covers ASAL counties only (DL-001).
- Forecast market sample is biased toward well-covered markets (DL-009).
- Climate aggregation method and boundaries are set by the publisher (DL-002).
- No live monthly price forecast from WFP data; recent town-market prices are sparse (DL-014)
- County rainfall for 39 counties is estimated from a sample of 1–4 sub-counties (DL-017).

---

## Entry template

```markdown
## DL-XXX — <short decision title>

**Date:** YYYY-MM-DD · **Status:** Proposed | Accepted | Open | Superseded by DL-XXX

**Context.** What problem or constraint forced a decision? What was known at the time?

**Decision.** What was chosen, stated precisely enough to check later.

**Alternatives considered.** Each option and why it was not chosen.

**Consequences.** What this makes easier, harder, or riskier. New limitations go to the running list.

**Revisit if.** The concrete trigger that would reopen this decision.
```
