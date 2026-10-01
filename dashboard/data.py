"""Read the marts the dashboard shows. Read-only: SELECT statements only.

The connection string comes from DATABASE_URL: the environment or .env locally,
st.secrets on Streamlit Community Cloud. Use a read-only database role.
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
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
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
