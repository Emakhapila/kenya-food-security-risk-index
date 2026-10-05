"""Tests for modelling/forecast_maize.py on synthetic prices (no database)."""
import numpy as np
import pandas as pd
import pytest

from modelling import forecast_maize as fm


def synthetic(n_counties=6, n_months=72, seed=3):
    rng = np.random.default_rng(seed)
    months = pd.date_range("2020-01-01", periods=n_months, freq="MS")
    cols = [f"KE{i:03d}" for i in range(n_counties)]
    season = 0.08 * np.sin(2 * np.pi * months.month / 12)
    y = pd.DataFrame({c: np.log(50 + 10 * i) + np.cumsum(rng.normal(0, 0.03, n_months)) + season
                      for i, c in enumerate(cols)}, index=months)
    clim = {k: pd.DataFrame(rng.normal(0, 0.3, y.shape), index=months, columns=cols)
            for k in ("rain1", "rain3", "ndvi")}
    return y, clim


@pytest.fixture(autouse=True)
def fewer_origins(monkeypatch):
    monkeypatch.setattr(fm, "INTERVAL_ORIGINS", 6)


def test_one_month_is_naive_and_ranges_contain_the_forecast():
    y, clim = synthetic()
    df, origin = fm.build(y, clim, low_res=set())
    assert origin == y.index.max()
    h1 = df[df["horizon"] == 1]
    assert (h1["forecast_kes_per_kg"] == h1["last_price_kes_per_kg"]).all()
    assert set(df["model"]) == {"naive", "lightgbm_climate"}
    assert (df["lower_80_kes_per_kg"] <= df["forecast_kes_per_kg"]).all()
    assert (df["forecast_kes_per_kg"] <= df["upper_80_kes_per_kg"]).all()
    assert len(df) == y.shape[1] * 3


def test_origin_ignores_a_month_only_one_county_has_reported():
    y, clim = synthetic()
    nxt = y.index.max() + pd.DateOffset(months=1)
    y.loc[nxt] = np.nan
    y.loc[nxt, "KE000"] = y["KE000"].iloc[-2]          # one early report
    clim = {k: v.reindex(y.index) for k, v in clim.items()}
    _, origin = fm.build(y, clim, low_res=set())
    assert origin == nxt - pd.DateOffset(months=1)


def test_county_without_a_price_at_origin_is_not_forecast():
    y, clim = synthetic()
    y.loc[y.index.max(), "KE005"] = np.nan
    df, _ = fm.build(y, clim, low_res=set())
    assert "KE005" not in set(df["county_pcode"])


def test_low_resolution_counties_are_flagged_and_left_out_of_the_ranges():
    y, clim = synthetic()
    df, _ = fm.build(y, clim, low_res={"KE000"})
    assert df.loc[df["county_pcode"] == "KE000", "is_low_resolution"].all()
    assert not df.loc[df["county_pcode"] != "KE000", "is_low_resolution"].any()
