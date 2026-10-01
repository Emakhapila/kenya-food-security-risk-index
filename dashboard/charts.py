"""Altair charts for the dashboard. Pure functions: data in, chart out.

Colours are the validated reference palette (light mode): orange and blue are a
warm/cool diverging pair around the "usual" midpoint, which is drawn in neutral
gray. Every mark has a hover tooltip; no chart has a second y-axis.
"""
from __future__ import annotations

import altair as alt
import pandas as pd

DRIER, WETTER = "#eb6834", "#2a78d6"
INDEX_LINE, IPC_LINE = "#2a78d6", "#eb6834"
NEUTRAL, GRID, TEXT_2 = "#52514e", "#e4e3df", "#52514e"


def _base(chart: alt.Chart) -> alt.Chart:
    return chart.configure_view(stroke=None).configure_axis(
        gridColor=GRID, domainColor=GRID, labelColor=TEXT_2, titleColor=TEXT_2,
        labelFontSize=12, titleFontSize=12, tickColor=GRID,
    ).configure_legend(labelColor=TEXT_2, titleColor=TEXT_2, orient="top")


def county_bars(snap: pd.DataFrame, selected: str | None = None) -> alt.Chart:
    """Diverging bars around 'usual' (0.5), one per county, most unusual first."""
    order = snap.sort_values("risk_index", ascending=False)["county_name"].tolist()
    d = snap.copy()
    sel = (selected or "").replace("'", "\\'")
    y = alt.Y("county_name:N", sort=order, title=None,
              axis=alt.Axis(labelLimit=140, ticks=False, domain=False, labelOverlap=False,
                            labelFontWeight=alt.ExprRef(f"datum.value == '{sel}' ? 'bold' : 'normal'"),
                            labelColor=alt.ExprRef(f"datum.value == '{sel}' ? '#0b0b0b' : '{TEXT_2}'"),
                            labelFontSize=alt.ExprRef(f"datum.value == '{sel}' ? 13 : 12")))
    bars = alt.Chart(d).mark_bar(cornerRadiusEnd=4, height={"band": 0.75}).encode(
        x=alt.X("deviation:Q", title="← wetter/greener than usual    drier/browner than usual →",
                scale=alt.Scale(domain=[-0.5, 0.5]),
                axis=alt.Axis(values=[-0.5, -0.25, 0, 0.25, 0.5],
                              labelExpr="datum.value == 0 ? 'usual' : format(datum.value + 0.5, '.2f')")),
        x2=alt.datum(0),
        y=y,
        color=alt.Color("direction:N", title=None,
                        legend=alt.Legend(orient="top", direction="vertical", labelLimit=260),
                        scale=alt.Scale(domain=["Drier/browner than usual", "Wetter/greener than usual"],
                                        range=[DRIER, WETTER])),
        tooltip=[
            alt.Tooltip("county_name:N", title="County"),
            alt.Tooltip("risk_index:Q", title="Risk index", format=".2f"),
            alt.Tooltip("risk_rain:Q", title="Rainfall component", format=".2f"),
            alt.Tooltip("risk_ndvi:Q", title="Vegetation component", format=".2f"),
            alt.Tooltip("climate_source_level:N", title="Climate data"),
        ],
    )
    rule = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color=NEUTRAL, strokeWidth=1).encode(x="x:Q")
    return _base(alt.layer(bars, rule).properties(height=max(24 * len(d), 200)))


def county_history(index: pd.DataFrame, ipc: pd.DataFrame, county: str,
                   start: str = "2019-01-01") -> tuple[alt.Chart, alt.Chart | None]:
    """Two panels on one timeline: monthly index, and IPC Phase 3+ share.

    Returned as two charts with the same date range so each can fill the page
    width; the IPC panel is None when IPC has no assessments for the county.
    """
    idx = index[(index["county_pcode"] == county) & (index["month"] >= start)].dropna(subset=["risk_index"])
    ipc_c = ipc[(ipc["county_pcode"] == county) & (ipc["analysis_month"] >= start)]
    x_dom = [pd.Timestamp(start).isoformat(), idx["month"].max().isoformat()]
    x_axis = alt.Axis(format="%Y", tickCount="year", labelAngle=0)
    x = alt.X("month:T", title=None, scale=alt.Scale(domain=x_dom), axis=x_axis)

    hover = alt.selection_point(fields=["month"], nearest=True, on="pointerover", empty=False)
    line = alt.Chart(idx).mark_line(color=INDEX_LINE, strokeWidth=2).encode(
        x=x, y=alt.Y("risk_index:Q", title="Risk index", scale=alt.Scale(domain=[0, 1]),
                     axis=alt.Axis(values=[0, 0.5, 1], minExtent=44)))
    points = alt.Chart(idx).mark_point(opacity=0).encode(
        x=x, y="risk_index:Q",
        tooltip=[alt.Tooltip("month:T", title="Month", format="%b %Y"),
                 alt.Tooltip("risk_index:Q", title="Risk index", format=".2f"),
                 alt.Tooltip("risk_rain:Q", title="Rainfall", format=".2f"),
                 alt.Tooltip("risk_ndvi:Q", title="Vegetation", format=".2f")]).add_params(hover)
    cross = alt.Chart(idx).mark_rule(color=NEUTRAL).encode(x=x).transform_filter(hover)
    usual = alt.Chart(pd.DataFrame({"y": [0.5]})).mark_rule(color=NEUTRAL, strokeDash=[]).encode(y="y:Q")
    top = alt.layer(usual, line, points, cross).properties(
        width="container", height=200, title=alt.TitleParams("Risk index (monthly; 0.5 = usual for this county)",
                                          anchor="start", fontSize=13, color="#0b0b0b"))

    if ipc_c.empty:
        return _base(top), None
    ipc_x = alt.X("analysis_month:T", title=None, scale=alt.Scale(domain=x_dom), axis=x_axis)
    ipc_line = alt.Chart(ipc_c).mark_line(color=IPC_LINE, strokeWidth=2,
                                          point=alt.OverlayMarkDef(size=80, filled=True, color=IPC_LINE,
                                                                   stroke="#fcfcfb", strokeWidth=2)).encode(
        x=ipc_x,
        y=alt.Y("share_phase3plus:Q", title="Phase 3+", axis=alt.Axis(format="%", minExtent=44)),
        tooltip=[alt.Tooltip("analysis_month:T", title="IPC analysis", format="%b %Y"),
                 alt.Tooltip("share_phase3plus:Q", title="People in Phase 3+", format=".0%"),
                 alt.Tooltip("is_partial_county:N", title="Covers part of county only")])
    bottom = ipc_line.properties(
        width="container", height=170, title=alt.TitleParams("People in IPC Phase 3+ (crisis or worse), each assessment",
                                          anchor="start", fontSize=13, color="#0b0b0b"))
    return _base(top), _base(bottom)
