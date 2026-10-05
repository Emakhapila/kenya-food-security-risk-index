"""Tests for the dashboard's data shaping and charts (no database, no Streamlit server)."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard"))
import charts  # noqa: E402
import data    # noqa: E402


def index_frame():
    months = pd.date_range("2025-01-01", "2025-06-01", freq="MS")
    rows = []
    for i, c in enumerate(["KE001", "KE002", "KE003", "KE004"]):
        for m in months:
            # the newest month is still arriving: only one county has it
            if m == months[-1] and c != "KE001":
                continue
            r = 0.2 + 0.2 * i
            rows.append({"county_pcode": c, "county_name": f"County {i}", "month": m,
                         "climate_source_level": "adm1", "risk_index": r,
                         "risk_rain": r, "risk_ndvi": r, "index_components": "rain+ndvi"})
    return pd.DataFrame(rows)


def ipc_frame():
    return pd.DataFrame({"county_pcode": ["KE001", "KE001"],
                         "analysis_month": pd.to_datetime(["2025-02-01", "2025-07-01"]),
                         "share_phase3plus": [0.1, 0.3], "is_partial_county": [False, False]})


def test_latest_month_skips_a_month_still_being_published():
    assert data.latest_complete_month(index_frame()) == pd.Timestamp("2025-05-01")


def test_snapshot_labels_direction_around_usual():
    snap = data.snapshot(index_frame(), pd.Timestamp("2025-05-01"))
    assert list(snap["risk_index"]) == sorted(snap["risk_index"], reverse=True)
    above = snap[snap["risk_index"] > 0.5]["direction"].unique().tolist()
    below = snap[snap["risk_index"] < 0.5]["direction"].unique().tolist()
    assert above == ["Drier/browner than usual"] and below == ["Wetter/greener than usual"]


def test_charts_build_and_ipc_panel_is_omitted_without_assessments():
    idx = index_frame()
    snap = data.snapshot(idx, pd.Timestamp("2025-05-01"))
    charts.county_bars(snap, selected="County 1").to_dict()
    top, bottom = charts.county_history(idx, ipc_frame(), "KE001", start="2025-01-01")
    top.to_dict(); bottom.to_dict()
    top, bottom = charts.county_history(idx, ipc_frame(), "KE002", start="2025-01-01")
    assert bottom is None


def test_selected_county_name_with_apostrophe_is_escaped():
    snap = data.snapshot(index_frame(), pd.Timestamp("2025-05-01"))
    spec = charts.county_bars(snap, selected="Murang'a").to_dict()
    axis = spec["layer"][0]["encoding"]["y"]["axis"]
    assert axis["labelFontWeight"]["expr"] == "datum.value == 'Murang\\'a' ? 'bold' : 'normal'"


def test_no_complete_month_raises():
    with pytest.raises(ValueError):
        data.latest_complete_month(index_frame().assign(risk_index=float("nan")))


def test_dashboard_prefers_the_read_only_connection(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "ROOT", tmp_path)          # no .env file
    monkeypatch.setenv("DATABASE_URL", "postgresql://owner@h/db")
    monkeypatch.setenv("DASHBOARD_DATABASE_URL", "postgresql://dashboard_reader@h/db")
    assert data.database_url() == "postgresql://dashboard_reader@h/db"
    monkeypatch.delenv("DASHBOARD_DATABASE_URL")
    assert data.database_url() == "postgresql://owner@h/db"


def forecast_frame():
    rows = []
    for c, name, last in (("KE001", "County 0", 50.0), ("KE002", "County 1", 80.0)):
        for h, (f, lo, hi) in {1: (last, last * .9, last * 1.1), 2: (last * .97, last * .85, last * 1.05),
                               3: (last * .95, last * .8, last * 1.04)}.items():
            rows.append({"county_pcode": c, "county_name": name,
                         "origin_month": pd.Timestamp("2025-05-01"),
                         "target_month": pd.Timestamp("2025-05-01") + pd.DateOffset(months=h),
                         "horizon": h, "model": "naive" if h == 1 else "lightgbm_climate",
                         "last_price_kes_per_kg": last, "forecast_kes_per_kg": f,
                         "lower_80_kes_per_kg": lo, "upper_80_kes_per_kg": hi,
                         "change_pct": round(100 * (f / last - 1), 1), "is_low_resolution": False})
    return pd.DataFrame(rows)


def test_forecast_table_has_one_row_per_county_and_a_3_month_range():
    t = data.forecast_table(forecast_frame())
    assert list(t.index) == ["County 0", "County 1"] or set(t.index) == {"County 0", "County 1"}
    assert t.index.name == "County"
    assert list(t.columns) == ["Latest", "In 3 months", "80% range", "Change, %"]
    assert t.loc["County 1", "80% range"] == "64–83"


def test_price_outlook_chart_builds():
    prices = pd.DataFrame({"county_pcode": "KE001",
                           "month": pd.date_range("2024-01-01", "2025-05-01", freq="MS"),
                           "price_kes_per_kg": 50.0})
    charts.price_outlook(prices, forecast_frame(), "KE001").to_dict()
