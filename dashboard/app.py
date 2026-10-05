"""Kenya Food Security Risk Index: public dashboard (DL-012).

A deliberately thin window into the marts: where conditions are unusual this
month, and how one county's index has moved alongside IPC assessments.

Run locally (from the repo root):
    streamlit run dashboard/app.py
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import charts  # noqa: E402
import data    # noqa: E402

REPO = "https://github.com/Emakhapila/kenya-food-security-risk-index"

st.set_page_config(page_title="Kenya Food Security Risk Index", page_icon="🌾", layout="wide")


@st.cache_data(ttl=6 * 3600, show_spinner="Loading the latest data…")
def load():
    return data.load_index(), data.load_ipc()


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_prices_and_forecast():
    return data.load_prices(), data.load_forecast()


try:
    index, ipc = load()
except Exception as exc:  # visitors see the error type; the full traceback goes to the app logs
    traceback.print_exc()
    st.error(f"Could not load data from the database: {type(exc).__name__}")
    st.stop()

month = data.latest_complete_month(index)
snap = data.snapshot(index, month)
validated = set(ipc.loc[~ipc["is_partial_county"], "county_pcode"])

st.title("Kenya Food Security Risk Index")
st.markdown(
    "How unusual each county's **rainfall and vegetation** are this month, compared with "
    "that county's own history. Higher means drier and browner than usual, the conditions "
    "that come before rising food insecurity in Kenya's drylands."
)

drier = int((snap["risk_index"] > 0.5).sum())
very = int((snap["risk_index"] >= 0.8).sum())
c1, c2, c3 = st.columns(3)
c1.metric("Data to", month.strftime("%B %Y"))
c2.metric("Counties drier/browner than usual", f"{drier} of {len(snap)}")
c3.metric("Strongly unusual (index ≥ 0.8)", f"{very}")

left, right = st.columns([5, 7], gap="large")

with left:
    st.subheader(f"All counties, {month.strftime('%B %Y')}")
    names = snap.sort_values("county_name")["county_name"].tolist()
    default = names.index("Marsabit") if "Marsabit" in names else 0
    county_name = st.selectbox("Choose a county", names, index=default)
    st.altair_chart(charts.county_bars(snap, selected=county_name), width="stretch")

with right:
    pcode = snap.loc[snap["county_name"] == county_name, "county_pcode"].iloc[0]
    row = snap[snap["county_pcode"] == pcode].iloc[0]
    st.subheader(county_name)
    st.markdown(
        f"Risk index **{row['risk_index']:.2f}** in {month.strftime('%B %Y')}: "
        f"{row['direction'].lower()} (0.5 = usual for {county_name})."
    )
    top, bottom = charts.county_history(index, ipc, pcode)
    st.altair_chart(top, width="stretch")
    if bottom is not None:
        st.altair_chart(bottom, width="stretch")
    if pcode not in validated:
        partial = bottom is not None
        st.info(
            (f"IPC's assessments for {county_name} cover only part of the county, so "
             if partial else f"IPC does not assess {county_name}, so ")
            + "the index has not been validated here. It still shows how unusual rainfall "
            "and vegetation are."
        )

st.divider()
st.header("Maize price outlook")
try:
    prices, fc = load_prices_and_forecast()
except Exception:
    traceback.print_exc()
    prices, fc = None, None

if fc is None or fc.empty:
    st.info("The price forecast has not been published yet.")
else:
    origin = fc["origin_month"].max()
    st.markdown(
        f"Retail white maize prices in the **16 counties** with FEWS NET price data, and the "
        f"forecast from **{origin:%B %Y}**. One month ahead, the forecast is the latest price: "
        f"in testing, nothing beat it. Two and three months ahead it comes from a model that "
        f"also uses rainfall and vegetation, which cut 3-month errors by about 7% in testing. "
        f"The 80% range shows how far off these forecasts have been over the last three years."
    )
    pcol, tcol = st.columns([7, 5], gap="large")
    with pcol:
        if pcode in set(fc["county_pcode"]):
            st.subheader(f"{county_name}")
            st.altair_chart(charts.price_outlook(prices, fc, pcode), width="stretch")
            if fc.loc[fc["county_pcode"] == pcode, "is_low_resolution"].any():
                st.caption(f"{county_name}'s prices are reported in coarse steps, so its "
                           "forecast is less reliable than the others.")
        else:
            st.info(f"There is no FEWS NET maize price series for {county_name}. "
                    "Choose one of the counties in the table to see its forecast.")
    with tcol:
        st.subheader("All 16 counties, KES/kg")
        st.dataframe(
            data.forecast_table(fc),
            width="stretch",
            height=35 * (fc["county_pcode"].nunique() + 1) + 3,
            column_config={
                "Latest": st.column_config.NumberColumn(format="%.0f"),
                "In 3 months": st.column_config.NumberColumn(format="%.0f"),
                "Change, %": st.column_config.NumberColumn(format="%+.1f"),
            },
        )

with st.expander("How to read this, and what it can't tell you"):
    st.markdown(f"""
- **What it measures.** Each month, the last 3 months of rainfall and the current vegetation
  greenness (NDVI) are ranked against the same time of year in every earlier year for that county.
  0.5 is a typical month; 1 is the driest/brownest on record.
- **How well it works.** In 19 counties assessed by IPC (2021–2026), the index tracked the share of
  people in IPC Phase 3+ within each county: Spearman ρ = 0.52 (95% CI 0.20 to 0.72). The test was
  written down before the index was built.
- **What it doesn't measure.**
  - Chronic food insecurity: it compares a county with its own past, not with other counties.
  - Flood risk: very wet seasons read as low risk even when floods damage crops and markets.
  - It uses observed data only, not rainfall forecasts.
- **Price forecasts.** The 80% range describes recent forecast errors; a shock unlike the last
  three years can fall outside it. The 2–3 month model's gain over "latest price" is consistent
  in testing but not yet proven.
- **Coverage.** Rainfall and vegetation for 39 counties are estimated from a sample of sub-counties.

Method, tests and every design decision: [GitHub repository]({REPO}) ·
[decision log]({REPO}/blob/main/docs/decisions.md)
""")

st.caption(
    "Sources: CHIRPS rainfall and MODIS NDVI (Climate Hazards Center, NASA and WFP, via HDX); "
    "IPC Kenya acute food insecurity (via HDX); retail maize prices from FEWS NET via FAO GIEWS FPMA "
    "(CC BY-NC-SA, shared under the same terms). Licences in the repository README. Built by Emmanuel."
)
