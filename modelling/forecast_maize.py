"""Publish the current retail maize price forecast (DL-021, DL-025).

Uses exactly the models the backtest evaluated (modelling/backtest_maize.py):
  1 month ahead      naive (last observed price); nothing beat it in the backtest
  2 and 3 months     LightGBM with rainfall and vegetation features

The forecast origin is the latest month in which at least half the counties have
a price (so one early report does not move it); a county is forecast only if it
has a price that month, as in the backtest.

80% ranges come from the models' own errors: the same models are re-run as a
rolling-origin forecast over the last 36 months, and the 10th and 90th
percentiles of log(actual / forecast) per horizon are applied to today's
forecast. They describe how wrong these forecasts have recently been, and
assume the next months will be no stranger than those.

Every run is appended to forecasts.maize_price_forecast_runs (nothing is
overwritten); marts.fct_price_forecast (dbt) shows the latest run.

Usage (from the repo root), after dbt has built the price and climate marts:
    python -m modelling.forecast_maize
    python scripts/run_dbt.py build --select fct_price_forecast
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from modelling.backtest_maize import (BASE_FEATURES, CLIMATE_FEATURES, HORIZONS, build_features,
                                      lightgbm_forecasts, load_climate, load_prices, to_wide)

INTERVAL_ORIGINS = 36
LOWER_Q, UPPER_Q = 0.10, 0.90
MODEL_BY_HORIZON = {1: "naive", 2: "lightgbm_climate", 3: "lightgbm_climate"}
TABLE = "forecasts.maize_price_forecast_runs"


def forecast_at(y: pd.DataFrame, feats: pd.DataFrame, origin: pd.Timestamp) -> dict:
    """{(county, h): log price forecast} from the published model for each horizon."""
    lgb = lightgbm_forecasts(y, feats, origin, BASE_FEATURES + CLIMATE_FEATURES)
    out = {}
    for c in y.columns:
        base = y[c].get(origin, np.nan)
        if np.isnan(base):
            continue
        for h in HORIZONS:
            out[(c, h)] = base if MODEL_BY_HORIZON[h] == "naive" else lgb.get((c, h), np.nan)
    return out


def error_quantiles(y: pd.DataFrame, feats: pd.DataFrame, origin: pd.Timestamp,
                    exclude: set[str]) -> pd.DataFrame:
    """Rolling-origin log errors of the published models over the last INTERVAL_ORIGINS months."""
    origins = pd.date_range(origin - pd.DateOffset(months=INTERVAL_ORIGINS),
                            origin - pd.DateOffset(months=1), freq="MS")
    errs = []
    for o in origins:
        for (c, h), f in forecast_at(y, feats, o).items():
            target = o + pd.DateOffset(months=h)
            actual = y[c].get(target, np.nan)
            if target <= origin and c not in exclude and not np.isnan(actual) and not np.isnan(f):
                errs.append({"horizon": h, "log_error": actual - f})
    e = pd.DataFrame(errs)
    q = e.groupby("horizon")["log_error"].quantile([LOWER_Q, UPPER_Q]).unstack()
    q.columns = ["q_low", "q_high"]
    q["n_errors"] = e.groupby("horizon").size()
    return q


def build(y: pd.DataFrame, clim: dict, low_res: set[str]) -> tuple[pd.DataFrame, pd.Timestamp]:
    observed = y.notna().sum(axis=1)
    origin = observed[observed >= 0.5 * y.shape[1]].index.max()   # most counties reported
    feats = build_features(y, clim)
    fc = forecast_at(y, feats, origin)
    q = error_quantiles(y, feats, origin, exclude=low_res)
    rows = []
    for (c, h), f in fc.items():
        if np.isnan(f):
            continue
        rows.append({
            "origin_month": origin.date(),
            "target_month": (origin + pd.DateOffset(months=h)).date(),
            "horizon": h,
            "county_pcode": c,
            "model": MODEL_BY_HORIZON[h],
            "last_price_kes_per_kg": round(float(np.exp(y[c][origin])), 2),
            "forecast_kes_per_kg": round(float(np.exp(f)), 2),
            "lower_80_kes_per_kg": round(float(np.exp(f + q.loc[h, "q_low"])), 2),
            "upper_80_kes_per_kg": round(float(np.exp(f + q.loc[h, "q_high"])), 2),
            "interval_errors_n": int(q.loc[h, "n_errors"]),
            "is_low_resolution": c in low_res,
        })
    return pd.DataFrame(rows), origin


def write(df: pd.DataFrame) -> str:
    import psycopg
    from dotenv import load_dotenv
    from modelling.backtest_maize import ROOT
    load_dotenv(ROOT / ".env")
    run_at = datetime.now(timezone.utc)
    cols = list(df.columns)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            with cur.copy(f"COPY {TABLE} (run_at, {', '.join(cols)}) FROM STDIN") as copy:
                for row in df.itertuples(index=False, name=None):
                    copy.write_row((run_at, *row))
        conn.commit()
    return run_at.isoformat(timespec="seconds")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="print the forecast without saving it")
    args = ap.parse_args()

    prices = load_prices()
    low_res = set(prices.loc[prices["is_low_resolution"], "county_pcode"])
    y = to_wide(prices)
    clim = load_climate(y)
    df, origin = build(y, clim, low_res)
    names = prices.drop_duplicates("county_pcode").set_index("county_pcode")["county_name"]

    pd.set_option("display.width", 200)
    show = df.assign(county=df["county_pcode"].map(names)).pivot(
        index="county", columns="horizon", values="forecast_kes_per_kg")
    print(f"Forecast from {origin:%B %Y} ({len(show)} counties), KES/kg:")
    print(show.rename(columns=lambda h: f"+{h} month").to_string())
    if args.dry_run:
        print("\n--dry-run: nothing saved")
        return
    run_at = write(df)
    print(f"\nSaved {len(df)} rows to {TABLE} (run {run_at})")


if __name__ == "__main__":
    main()
