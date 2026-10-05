"""Read the marts the dashboard shows. Read-only: SELECT statements only.

The connection string comes from DASHBOARD_DATABASE_URL (the read-only role) if
set, otherwise DATABASE_URL: from the environment or .env locally, st.secrets on
Streamlit Community Cloud. The public app always uses the read-only role.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
COMPLETE_SHARE = 0.9   # a month counts as published once 90% of counties have a value


def database_url() -> str:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    for name in ("DASHBOARD_DATABASE_URL", "DATABASE_URL"):
        if os.environ.get(name):
            return os.environ[name]
    import streamlit as st
    return st.secrets["DATABASE_URL"]


def query(sql: str, params: tuple = ()) -> pd.DataFrame:
    import psycopg
    with psycopg.connect(database_url()) as conn:
        cur = conn.execute(sql, params)
        return pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])


def load_index() -> pd.DataFrame:
    df = query("""
        SELECT county_pcode, county_name, month, climate_source_level,
               risk_index, risk_rain, risk_ndvi, index_components
        FROM marts.fct_risk_index_monthly
        WHERE month >= date '2015-01-01'
    """)
    df["month"] = pd.to_datetime(df["month"])
    for c in ("risk_index", "risk_rain", "risk_ndvi"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    return df


def load_ipc() -> pd.DataFrame:
    df = query("""
        SELECT county_pcode, analysis_month, share_phase3plus, is_partial_county
        FROM marts.fct_ipc_county_analysis
    """)
    df["analysis_month"] = pd.to_datetime(df["analysis_month"])
    df["share_phase3plus"] = df["share_phase3plus"].astype(float)
    df["is_partial_county"] = df["is_partial_county"].astype(bool)
    return df


def latest_complete_month(index: pd.DataFrame, share: float = COMPLETE_SHARE) -> pd.Timestamp:
    """Latest month with a value for at least `share` of counties.

    The newest month is often still being published (rainfall arrives by dekad,
    NDVI later), so its first few counties should not be shown as the latest map.
    """
    counts = index.dropna(subset=["risk_index"]).groupby("month")["county_pcode"].nunique()
    full = index["county_pcode"].nunique()
    ok = counts[counts >= share * full]
    if ok.empty:
        raise ValueError("no month has enough counties with a risk index")
    return ok.index.max()


def snapshot(index: pd.DataFrame, month: pd.Timestamp) -> pd.DataFrame:
    """One row per county for one month, with a plain-language direction."""
    s = index[index["month"] == month].dropna(subset=["risk_index"]).copy()
    s["deviation"] = s["risk_index"] - 0.5
    s["direction"] = s["deviation"].map(
        lambda d: "Drier/browner than usual" if d > 0 else "Wetter/greener than usual")
    return s.sort_values("risk_index", ascending=False).reset_index(drop=True)


def load_forecast() -> pd.DataFrame:
    df = query("""
        SELECT county_pcode, county_name, origin_month, target_month, horizon, model,
               last_price_kes_per_kg, forecast_kes_per_kg, lower_80_kes_per_kg,
               upper_80_kes_per_kg, change_pct, is_low_resolution
        FROM marts.fct_price_forecast
    """)
    for c in ("origin_month", "target_month"):
        df[c] = pd.to_datetime(df[c])
    for c in ("last_price_kes_per_kg", "forecast_kes_per_kg", "lower_80_kes_per_kg",
              "upper_80_kes_per_kg", "change_pct"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    return df


def load_prices(months: int = 36) -> pd.DataFrame:
    df = query("""
        SELECT county_pcode, month, price_kes_per_kg
        FROM marts.fct_maize_price_monthly
        WHERE price_kes_per_kg IS NOT NULL
          AND month >= (SELECT max(month) FROM marts.fct_maize_price_monthly)
                       - make_interval(months => %s)
    """, (months,))
    df["month"] = pd.to_datetime(df["month"])
    df["price_kes_per_kg"] = df["price_kes_per_kg"].astype(float)
    return df


def forecast_table(fc: pd.DataFrame) -> pd.DataFrame:
    """One row per county: latest price and the 3-month forecast with its range.

    The 1-month forecast is the latest price (naive), so it is not repeated.
    """
    h3 = fc[fc["horizon"] == 3].set_index("county_name")
    last = fc.drop_duplicates("county_name").set_index("county_name")["last_price_kes_per_kg"]
    out = pd.DataFrame({
        "Latest": last,
        "In 3 months": h3["forecast_kes_per_kg"],
        "80% range": h3["lower_80_kes_per_kg"].round(0).astype("Int64").astype(str)
                                 + "–" + h3["upper_80_kes_per_kg"].round(0).astype("Int64").astype(str),
        "Change, %": h3["change_pct"],
    })
    out.index.name = "County"
    return out.sort_values("Change, %", ascending=False)
