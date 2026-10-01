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
