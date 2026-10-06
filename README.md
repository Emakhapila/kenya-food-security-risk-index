# Kenya Food Security Risk Index

[![CI](https://github.com/Emakhapila/kenya-food-security-risk-index/actions/workflows/ci.yml/badge.svg)](https://github.com/Emakhapila/kenya-food-security-risk-index/actions/workflows/ci.yml)

**Live dashboard: [kenya-food-security-index.streamlit.app](https://kenya-food-security-index.streamlit.app/)**, updated monthly.

An end-to-end data pipeline that brings together maize prices, rainfall, vegetation and official food security assessments for Kenya's counties. It builds a monthly county risk index, validated against the official IPC assessments, and publishes a monthly maize price forecast after testing whether climate signals improve it.

Food crises in Kenya's arid and semi-arid counties build up over months, but the official IPC assessments are published about twice a year. The signals in between (prices, rainfall, pasture) are spread across sources with different formats, geographies and schedules. This project reconciles them into one tested, county-level warehouse that refreshes monthly.

## Headline results

### 1. The risk index tracks IPC food insecurity

A monthly index ranks each county's recent rainfall, vegetation and maize prices against its own history (DL-022). The validation test was fixed in the decision log before any results existed. Across 12 IPC analyses (2021–2026) and 19 counties:

| Within-county correlation with the IPC Phase 3+ share | Spearman ρ | 95% interval |
|---|---|---|
| Rainfall only | 0.42 | 0.12 to 0.64 |
| **Rainfall + vegetation (primary)** | **0.52** | **0.20 to 0.72** |
| Rainfall + vegetation + price (13 FEWS NET counties) | 0.60 | 0.26 to 0.75 |

![Marsabit County: monthly risk index and IPC Phase 3+ share](reports/figures/index_vs_ipc_marsabit.png)

*Marsabit is a typical county: its correlation (0.68) is close to the median of the 19 validated counties (0.66). Made with [`modelling/plot_index_example.py`](modelling/plot_index_example.py).*

- **When a county's index rises, its share of people in IPC Phase 3+ tends to rise too.** The index averages the 3 months before each assessment, so it uses only information available before IPC published.
- **Vegetation adds to rainfall** (+0.11), but the interval (−0.003 to +0.21) just includes zero: consistent evidence, not proof.
- **Price adds nothing** once rainfall and vegetation are in (−0.02). The price variant scores higher only because it covers different counties.
- The index measures shocks relative to each county's own history, not chronic food insecurity, so the test removes each county's average first.

### 2. Climate signals help 3-month maize price forecasts

Forecasting retail maize prices in 16 mostly arid and semi-arid counties, with a leakage-tested rolling-origin backtest (60 monthly origins, July 2021 to June 2026, including the 2021–2023 drought):

| 3 months ahead | MAE (KES/kg) | MAPE |
|---|---|---|
| Naive (last observed price) | 6.73 | 10.7% |
| SARIMAX | 6.84 | 10.8% |
| LightGBM, price history only | 6.83 | 10.7% |
| **LightGBM + rainfall and vegetation anomalies** | **6.34** | **9.9%** |

- **Price history alone does not beat a naive forecast** at 1–3 months. Over these horizons, retail maize prices behave close to a random walk.
- **Adding rainfall and NDVI anomalies cuts LightGBM's 3-month error by about 7%**, an almost identical improvement to a separate 24-month test. The 95% bootstrap interval (−1.02 to +0.01 KES/kg) just includes zero, so this is consistent evidence rather than proof.
- **The same climate data does not help SARIMAX**, which suggests the drought effect on prices is non-linear.
- **At 1 month ahead, nothing beats naive**, which remains the published 1-month forecast.

Full numbers and reasoning: DL-020 to DL-023 in the [decision log](docs/decisions.md). Summary metrics are in [`reports/index_validation/`](reports/index_validation/) and [`reports/backtest/`](reports/backtest/).

## Architecture

```mermaid
flowchart LR
    subgraph Sources
        A[WFP market prices<br/>HDX]
        B[FEWS NET retail maize<br/>via FAO GIEWS FPMA]
        C[CHIRPS rainfall<br/>WFP, HDX]
        D[MODIS NDVI<br/>WFP, HDX]
        E[IPC assessments<br/>HDX]
    end
    subgraph "PostgreSQL (Neon)"
        R[(raw<br/>append-only,<br/>row-hash dedup)]
        S[(staging<br/>typed, latest version,<br/>county-conformed)]
        M[(marts<br/>county × month)]
        REF[(reference<br/>47 counties,<br/>name aliases)]
    end
    Sources -->|Python ingestion<br/>load log| R
    R -->|dbt| S --> M
    REF --> S
    M --> F[Backtest<br/>naive · SARIMAX · LightGBM]
```

| Layer | What it does | Where |
|---|---|---|
| Ingestion | Downloads the HDX sources through HDX's API (FPMA is a manual export); loads each file; skips unchanged files; stores each distinct row once, so revised values arrive as new rows and nothing is overwritten. Every run is logged. | [`ingest/`](ingest/) |
| Reference | Official 47 counties with 2019 census population, and a table mapping every source's county spelling to an official code. The build fails if a source name is unmapped. | [`scripts/build_reference.py`](scripts/build_reference.py), [`dbt/seeds/`](dbt/seeds/) |
| Staging | Types every column, keeps the latest version of each value, maps counties to official codes. | [`dbt/models/staging/`](dbt/models/staging/) |
| Marts | Monthly maize price per county (every month present, gaps explicit, flat runs flagged); monthly rainfall and vegetation per county with anomalies; IPC Phase 3+ share per county per analysis; monthly county risk index (rainfall and vegetation percentiles against each county's own history; price kept for analysis) and its alignment to each IPC analysis; the latest published maize price forecast. | [`dbt/models/marts/`](dbt/models/marts/) |
| Modelling | Rolling-origin backtest of six forecasting approaches with bootstrap confidence intervals; validation of the risk index against IPC, as pre-registered in DL-022. | [`modelling/`](modelling/) |

## What the data required

Most of the work was in understanding the sources before loading them. Some of the findings, each recorded in the [decision log](docs/decisions.md):

- **WFP's `admin1` is the old province, not the county.** Counties are in `admin2`.
- **WFP maize series were renamed around 2020 with new market IDs**, and the old and new series could not be joined reliably (DL-014).
- **The only dense recent WFP retail series were refugee camps** (Kakuma, Kalobeyei, Dadaab), where prices follow aid distributions rather than local conditions. Markets are classified as town, urban informal or camp, and the index uses town markets only (DL-015).
- **FEWS NET retail maize (via FAO FPMA) covers 16 counties from 2010 to 2026** at 95–97% completeness, and became the forecasting dataset (DL-016).
- **Rainfall and NDVI cover only 8 counties directly**; the other 39 are estimated from a sample of sub-counties, weighted by area (DL-017).
- **Seven IPC areas cover only the drier part of their county**, found by comparing IPC's population with the 2019 census (DL-018).
- **FEWS NET published no prices from February to July 2023.** The backtest only forecasts from months with an observed price, so every model is compared on identical cases.

## Methodology notes

- **Leakage control:** features use only data up to the forecast origin; LightGBM trains only on rows whose target month is on or before the origin; and a test that corrupts all data after an origin confirms that origin's forecasts don't change.
- **LightGBM predicts log price changes, not levels**, because tree models cannot extrapolate beyond the prices seen in training, and maize prices trend upwards.
- **Climate enters with care over timing:** SARIMAX uses anomalies lagged 3 months, so 1–3 month forecasts never need future climate values.
- **Confidence intervals** resample forecast origins rather than individual forecasts, because counties in the same month share market conditions.
- **Missing months are not imputed.** Both SARIMAX and LightGBM handle gaps directly; filling them would invent data.

## Limitations

**Risk index**
- It measures **shocks**: how unusual conditions are for a county compared with its own history. It does not measure chronic food insecurity, so it cannot rank how food-insecure counties are relative to each other (DL-022).
- It measures **drought, not floods**. Rainfall counts in one direction, so a very wet season reads as low risk even when floods damage crops and markets (for example, the late-2023 El Niño rains). It uses observed data only, not rainfall forecasts.
- It is **validated only where IPC assesses whole counties**: 19 dryland counties, 12 assessments (2021–2026). Elsewhere it is unvalidated. The test shows the index moves with IPC within counties; it is not a forecast of Phase 3+ levels, and 12 assessments give wide intervals (DL-023).
- Rainfall and vegetation for 39 counties are **estimated from 1–4 sub-counties**, using the publisher's own aggregation (DL-002, DL-017).

**Price forecast**
- It covers **16 mostly dryland counties**, those with FEWS NET retail maize prices (DL-016).
- FEWS NET has no API, so prices are **exported by hand each month**. The forecast is only as current as the last export.
- At 2–3 months, the gain over "latest price" is **consistent but not proven**: the 95% interval just includes zero (DL-021).
- The 80% ranges come from the last three years of errors, so a shock unlike those years can fall outside them (DL-025). Garissa's prices are reported in coarse steps, so its forecast is less reliable.

**Pipeline**
- The raw layer stores every version of every row but cannot tell a row deleted at the source from an unchanged one. A test stops the build if this would double-count an IPC area (DL-019).
- It runs on free tiers. The dashboard sleeps when unused and takes about 30 seconds to wake.

The [decision log](docs/decisions.md) keeps the full running list, with the evidence for each item.

## Scope of v1

**In v1:**
- data pipeline, warehouse and tests;
- the risk index and its pre-registered validation;
- the price backtest and the published monthly forecast;
- the live dashboard;
- automatic monthly refresh;
- a written AWS target architecture.

**Planned for v2,** each to be validated before it is published:
- a separate excess-rainfall (flood) signal;
- a projected index driven by seasonal rainfall forecasts;
- WFP price staging for town markets;
- deploying the [AWS architecture](docs/aws-architecture.md);
- an API.

## Running it

Requirements: Python 3.11 and a PostgreSQL database.

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows; use source .venv/bin/activate on Linux/macOS
python -m pip install -r requirements.txt
# create a .env file in the repo root containing:
# DATABASE_URL=postgresql://user:password@host/dbname?sslmode=require

python scripts/build_reference.py            # county reference tables
python -m ingest.run --download              # download HDX sources, then load all raw sources
                                             # (FPMA: put the manual export in data/raw_manual/)
python scripts/run_dbt.py build              # staging, marts and tests
python -m modelling.backtest_maize --test-months 60
python -m modelling.validate_index          # risk index vs IPC (DL-022)
python -m modelling.forecast_maize           # publish the maize price forecast (DL-025)
python scripts/run_dbt.py build --select fct_price_forecast
streamlit run dashboard/app.py               # dashboard at http://localhost:8501
python -m pytest tests/
```

`scripts/run_dbt.py` reads the connection from `DATABASE_URL`, so the credentials live in one place.

**Automation** ([`.github/workflows/`](.github/workflows/)): every pull request runs the tests and parses the dbt project. On the 8th of each month a scheduled run downloads the HDX sources, rebuilds the warehouse on Neon and publishes the price forecast and re-runs the index validation, attaching the results to the run. It needs one repository secret, `DATABASE_URL`. FEWS NET/FPMA prices have no API and are exported and loaded by hand each month.

## Data sources and licences

| Source | Provider | Licence |
|---|---|---|
| Food prices | WFP, via HDX | CC BY-IGO |
| Retail maize prices | FEWS NET, via FAO GIEWS FPMA | CC BY-NC-SA |
| Rainfall (CHIRPS) | Climate Hazards Center & WFP, via HDX | CC BY |
| NDVI (MODIS) | NASA & WFP, via HDX | see HDX dataset page |
| IPC acute food insecurity | National IPC Technical Working Group, via HDX | see HDX dataset page |
| Administrative boundaries and population | OCHA, via HDX (population: KNBS 2019 census) | see HDX dataset page |

Raw data is not included in this repository. The FEWS NET/FPMA data is licensed for non-commercial use, and any derived data is shared under the same terms.

## Status

**Done:** source profiling, reference tables, raw ingestion, dbt staging and marts for prices, climate and IPC, the county risk index (DL-022), forecasting backtest with climate features, risk index validated against IPC, automatic HDX downloads, CI and a scheduled monthly refresh, a published monthly price forecast (DL-025), a live dashboard, a written AWS target architecture (DL-013). **v1 is complete.**

**Next:** see [Scope of v1](#scope-of-v1) for what v2 adds.

## Documentation

- [Decision log](docs/decisions.md): every significant design decision, with the evidence behind it
- [Data sources](docs/data-sources.md): what each source contains and the problems found in profiling
- [AWS target architecture](docs/aws-architecture.md): how the pipeline would run on AWS, with a monthly cost estimate (v2)

---

Built by Emmanuel · [GitHub](https://github.com/Emakhapila)
