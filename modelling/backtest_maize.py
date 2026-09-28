"""Rolling-origin backtest of retail maize price forecasts (DL-010, DL-016, DL-020).

Models, all forecasting log price 1-3 months ahead from the same information:
  naive             last observed price
  seasonal_naive    price in the same month one year earlier
  sarimax           per-county SARIMAX(1,1,1)(1,0,0,12) on log price, refit at every origin
  sarimax_climate   the same, plus rainfall and NDVI anomalies lagged 3 months as
                    exogenous inputs (so forecasts up to 3 months ahead need no
                    future climate values)
  lightgbm          one global model per horizon across all counties, predicting the
                    log change from the origin month (not the level: trees cannot
                    extrapolate beyond prices seen in training)
  lightgbm_climate  the same, plus rainfall and NDVI anomaly features

Forecasts are made only for county-months with an observed price at the origin,
so every model is compared on the same cases (no origins inside the 2023 gap).
At each origin only data up to and including the origin month is used, and
LightGBM trains only on rows whose target month is on or before the origin.
Climate for month t is assumed available when month t's price is (both are
published early in the following month). Errors are on the price scale
(KES/kg). Differences from naive get a 95% bootstrap interval over origins.
Low-resolution series (Garissa, DL-016) are reported separately.

Usage (from the repo root):
    python -m modelling.backtest_maize
    python -m modelling.backtest_maize --no-climate
"""
from __future__ import annotations

import argparse
import os
import time
import warnings
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from statsmodels.tools.sm_exceptions import ConvergenceWarning
from statsmodels.tsa.statespace.sarimax import SARIMAX

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "backtest"
FORECAST_DIR = ROOT / "data" / "outputs"          # derived from licensed data; not committed
HORIZONS = (1, 2, 3)
EXOG_LAG = 3                                      # must be >= max(HORIZONS)
SARIMAX_ORDER = (1, 1, 1)
SARIMAX_SEASONAL = (1, 0, 0, 12)
LGB_PARAMS = dict(
    n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20,
    subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
    random_state=42, verbose=-1,
)
BASE_FEATURES = ["r1", "r3", "r6", "r12", "dev12", "vol6", "rel_level",
                 "nat_r1", "nat_r3", "target_month", "county"]
CLIMATE_FEATURES = ["rain1", "rain3", "ndvi", "ndvi_d1", "rain3_l3", "ndvi_l3", "nat_rain3", "nat_ndvi"]
CLIMATE_VARS = {"rain_1m_anom_pct": "rain1", "rain_3m_anom_pct": "rain3", "ndvi_anom_pct": "ndvi"}


# ---------------------------------------------------------------- data

def _query(sql: str, cols: list[str]) -> pd.DataFrame:
    import psycopg
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        return pd.DataFrame(conn.execute(sql).fetchall(), columns=cols)


def load_prices() -> pd.DataFrame:
    cols = ["county_pcode", "county_name", "month", "price_kes_per_kg", "is_low_resolution"]
    df = _query(f"SELECT {', '.join(cols)} FROM marts.fct_maize_price_monthly", cols)
    df["month"] = pd.to_datetime(df["month"])
    df["price_kes_per_kg"] = pd.to_numeric(df["price_kes_per_kg"], errors="coerce").astype(float)
    df["is_low_resolution"] = df["is_low_resolution"].astype(bool)
    return df


def load_climate(y: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Climate anomalies as fractions of normal (0 = normal, -0.5 = half of normal), wide like y."""
    cols = ["county_pcode", "month", *CLIMATE_VARS]
    df = _query(f"SELECT {', '.join(cols)} FROM marts.fct_climate_county_monthly "
                f"WHERE rain_month_complete", cols)
    df["month"] = pd.to_datetime(df["month"])
    out = {}
    for col, short in CLIMATE_VARS.items():
        wide = df.pivot(index="month", columns="county_pcode", values=col).astype(float)
        wide = (wide / 100 - 1).clip(-1, 3)        # cap extreme ratios from near-zero averages
        out[short] = wide.reindex(index=y.index, columns=y.columns)
    return out


def to_wide(df: pd.DataFrame) -> pd.DataFrame:
    """Months x counties of log price, on a complete monthly index."""
    wide = df.pivot(index="month", columns="county_pcode", values="price_kes_per_kg").asfreq("MS")
    return np.log(wide)


# ---------------------------------------------------------------- features for LightGBM

def build_features(y: pd.DataFrame, clim: dict | None) -> pd.DataFrame:
    """Long frame of features known at month t, one row per county and month."""
    r1 = y.diff(1)
    frames = {
        "r1": r1, "r3": y.diff(3), "r6": y.diff(6), "r12": y.diff(12),
        "dev12": y - y.rolling(12, min_periods=6).mean(),
        "vol6": r1.rolling(6, min_periods=3).std(),
        "rel_level": y.sub(y.mean(axis=1), axis=0),
    }
    national = {"nat_r1": r1.mean(axis=1), "nat_r3": y.diff(3).mean(axis=1)}
    if clim:
        frames.update({
            "rain1": clim["rain1"], "rain3": clim["rain3"], "ndvi": clim["ndvi"],
            "ndvi_d1": clim["ndvi"].diff(1),
            "rain3_l3": clim["rain3"].shift(3), "ndvi_l3": clim["ndvi"].shift(3),
        })
        national.update({"nat_rain3": clim["rain3"].mean(axis=1), "nat_ndvi": clim["ndvi"].mean(axis=1)})
    long = pd.concat({k: v.stack(future_stack=True) for k, v in frames.items()}, axis=1)
    long.index.names = ["month", "county_pcode"]
    long = long.reset_index()
    for k, v in national.items():
        long[k] = long["month"].map(v)
    long["y"] = y.stack(future_stack=True).values
    long["county"] = long["county_pcode"].astype("category")
    return long


def lightgbm_forecasts(y: pd.DataFrame, feats: pd.DataFrame, origin: pd.Timestamp,
                       features: list[str]) -> dict:
    """Return {(county, h): forecast log price} for one origin."""
    out = {}
    at_origin = feats[(feats["month"] == origin) & feats["y"].notna()]
    if at_origin.empty:                 # no county has a price this month (e.g. the 2023 gap)
        return out
    for h in HORIZONS:
        f = feats.copy()
        f["target"] = y.shift(-h).stack(future_stack=True).values - f["y"].values
        f["target_month"] = (f["month"] + pd.DateOffset(months=h)).dt.month
        train = f[(f["month"] + pd.DateOffset(months=h) <= origin) & f["target"].notna()]
        model = lgb.LGBMRegressor(**LGB_PARAMS)
        model.fit(train[features], train["target"], categorical_feature=["county"])
        x = at_origin.copy()
        x["target_month"] = (origin + pd.DateOffset(months=h)).month
        for c, base, p in zip(x["county_pcode"], x["y"], model.predict(x[features])):
            out[(c, h)] = base + p
    return out


# ---------------------------------------------------------------- other models

def sarimax_forecasts(s: pd.Series, origin: pd.Timestamp, exog: pd.DataFrame | None = None) -> dict:
    """exog, if given, is indexed like s and already lagged by EXOG_LAG months."""
    train = s.loc[:origin]
    ex_train = ex_future = None
    if exog is not None:
        ex_train = exog.loc[:origin]
        future_idx = pd.date_range(origin + pd.DateOffset(months=1), periods=max(HORIZONS), freq="MS")
        ex_future = exog.reindex(future_idx)
        if ex_future.isna().any().any():   # only possible if EXOG_LAG < horizon
            raise ValueError("future exogenous values missing")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        warnings.simplefilter("ignore", UserWarning)
        res = SARIMAX(train, exog=ex_train, order=SARIMAX_ORDER, seasonal_order=SARIMAX_SEASONAL,
                      enforce_stationarity=False, enforce_invertibility=False
                      ).fit(disp=False, maxiter=200)
    fc = res.forecast(steps=max(HORIZONS), exog=ex_future)
    return {h: float(fc.iloc[h - 1]) for h in HORIZONS}


def sarimax_exog(clim: dict, county: str, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Rainfall (3-month) and NDVI anomalies, lagged EXOG_LAG months; gaps set to normal (0)."""
    ext = pd.date_range(index.min(), index.max() + pd.DateOffset(months=max(HORIZONS)), freq="MS")
    ex = pd.DataFrame({"rain3": clim["rain3"][county], "ndvi": clim["ndvi"][county]})
    return ex.reindex(ext).shift(EXOG_LAG).fillna(0.0)


# ---------------------------------------------------------------- backtest

def run_backtest(y: pd.DataFrame, clim: dict | None, test_months: int) -> pd.DataFrame:
    last = y.index.max()
    origins = pd.date_range(last - pd.DateOffset(months=test_months),
                            last - pd.DateOffset(months=1), freq="MS")
    feats = build_features(y, clim)
    exogs = {c: sarimax_exog(clim, c, y.index) for c in y.columns} if clim else {}
    rows = []
    for i, origin in enumerate(origins, 1):
        t0 = time.perf_counter()
        lgb_fc = lightgbm_forecasts(y, feats, origin, BASE_FEATURES)
        lgb_cl = lightgbm_forecasts(y, feats, origin, BASE_FEATURES + CLIMATE_FEATURES) if clim else {}
        for c in y.columns:
            s = y[c]
            if np.isnan(s.get(origin, np.nan)):
                continue                    # forecast only from months with an observed price
            base = s[origin]
            fits = {"sarimax": None, "sarimax_climate": exogs.get(c)} if clim else {"sarimax": None}
            sar = {}
            for name, ex in fits.items():
                try:
                    sar[name] = sarimax_forecasts(s, origin, ex)
                except Exception:                   # rare numerical failure: record as missing
                    sar[name] = {h: np.nan for h in HORIZONS}
            for h in HORIZONS:
                target = origin + pd.DateOffset(months=h)
                if target > last:
                    continue
                row = {
                    "origin": origin, "target_month": target, "horizon": h, "county_pcode": c,
                    "actual": s.get(target, np.nan),
                    "naive": base,
                    "seasonal_naive": s.get(target - pd.DateOffset(months=12), np.nan),
                    "sarimax": sar["sarimax"][h],
                    "lightgbm": lgb_fc[(c, h)],
                }
                if clim:
                    row["sarimax_climate"] = sar["sarimax_climate"][h]
                    row["lightgbm_climate"] = lgb_cl[(c, h)]
                rows.append(row)
        print(f"  origin {origin:%Y-%m} ({i}/{len(origins)}) {time.perf_counter() - t0:.1f}s", flush=True)
    fc = pd.DataFrame(rows)
    value_cols = [c for c in fc.columns if c not in ("origin", "target_month", "horizon", "county_pcode")]
    fc[value_cols] = np.exp(fc[value_cols])          # back to KES/kg
    return fc


# ---------------------------------------------------------------- scoring

def score(fc: pd.DataFrame, models: list[str], by: list[str]) -> pd.DataFrame:
    fc = fc.dropna(subset=["actual"])
    out = []
    for keys, g in fc.groupby(by):
        keys = keys if isinstance(keys, tuple) else (keys,)
        row = dict(zip(by, keys), n=len(g))
        for m in models:
            err = (g[m] - g["actual"]).abs()
            row[f"{m}_mae"] = err.mean()
            row[f"{m}_mape"] = (err / g["actual"]).mean() * 100
        for m in models:
            if m not in ("naive", "seasonal_naive"):
                row[f"{m}_skill_vs_naive"] = 1 - row[f"{m}_mae"] / row["naive_mae"]
        out.append(row)
    return pd.DataFrame(out)


def bootstrap_diff(fc: pd.DataFrame, model: str, reference: str, reps: int = 2000,
                   seed: int = 0) -> pd.DataFrame:
    """MAE(model) - MAE(reference) per horizon, with a 95% interval from resampling origins.

    Origins, not individual forecasts, are resampled, because all counties at one
    origin share the same market conditions. Negative = model is better.
    """
    rng = np.random.default_rng(seed)
    fc = fc.dropna(subset=["actual", model, reference])
    rows = []
    for h, g in fc.groupby("horizon"):
        per_origin = g.assign(d=(g[model] - g["actual"]).abs() - (g[reference] - g["actual"]).abs()
                              ).groupby("origin")["d"].mean().values
        boots = rng.choice(per_origin, size=(reps, len(per_origin)), replace=True).mean(axis=1)
        lo, hi = np.percentile(boots, [2.5, 97.5])
        rows.append({"model": model, "reference": reference, "horizon": h,
                     "mae_diff": per_origin.mean(), "ci_low": lo, "ci_high": hi,
                     "clear": "better" if hi < 0 else ("worse" if lo > 0 else "no clear difference")})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--test-months", type=int, default=24)
    ap.add_argument("--no-climate", action="store_true", help="skip the climate-feature models")
    args = ap.parse_args()

    df = load_prices()
    names = df.drop_duplicates("county_pcode").set_index("county_pcode")["county_name"]
    low_res = set(df.loc[df["is_low_resolution"], "county_pcode"])
    y = to_wide(df)
    clim = None if args.no_climate else load_climate(y)
    models = ["naive", "seasonal_naive", "sarimax", "lightgbm"]
    if clim:
        models = ["naive", "seasonal_naive", "sarimax", "sarimax_climate", "lightgbm", "lightgbm_climate"]
        coverage = {k: v.loc[:, ~y.columns.isin(low_res)].notna().mean().mean() for k, v in clim.items()}
        print("climate coverage:", {k: f"{v:.0%}" for k, v in coverage.items()})
    print(f"{y.shape[1]} counties, {y.index.min():%Y-%m} to {y.index.max():%Y-%m}; "
          f"testing the last {args.test_months} origins")

    fc = run_backtest(y, clim, args.test_months)
    fc["county_name"] = fc["county_pcode"].map(names)
    fc["series_group"] = np.where(fc["county_pcode"].isin(low_res), "low_resolution", "main")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    FORECAST_DIR.mkdir(parents=True, exist_ok=True)
    fc.to_csv(FORECAST_DIR / "backtest_forecasts.csv", index=False)
    by_h = score(fc, models, ["series_group", "horizon"])
    by_c = score(fc, models, ["series_group", "county_name", "horizon"])
    main_fc = fc[fc["series_group"] == "main"]
    pairs = [(m, "naive") for m in models if m not in ("naive", "seasonal_naive")]
    if clim:
        pairs += [("sarimax_climate", "sarimax"), ("lightgbm_climate", "lightgbm")]
    diffs = pd.concat([bootstrap_diff(main_fc, m, r) for m, r in pairs], ignore_index=True)
    by_h.round(3).to_csv(REPORT_DIR / "metrics_by_horizon.csv", index=False)
    by_c.round(3).to_csv(REPORT_DIR / "metrics_by_county.csv", index=False)
    diffs.round(3).to_csv(REPORT_DIR / "differences_with_intervals.csv", index=False)

    main_h = by_h[by_h["series_group"] == "main"].set_index("horizon")
    pd.set_option("display.width", 200)
    print("\nMAE, KES per kg (main series; lower is better)")
    print(main_h[[f"{m}_mae" for m in models]].round(2).rename(columns=lambda c: c[:-4]).to_string())
    print("\nMAPE, % (main series)")
    print(main_h[[f"{m}_mape" for m in models]].round(1).rename(columns=lambda c: c[:-5]).to_string())
    print("\nDifference in MAE (KES/kg) with 95% bootstrap interval over origins; negative = better")
    for _, r in diffs.iterrows():
        print(f"  {r['model']:17s} vs {r['reference']:8s} h={r['horizon']}: "
              f"{r['mae_diff']:+.2f} [{r['ci_low']:+.2f}, {r['ci_high']:+.2f}]  {r['clear']}")

    c1 = by_c[(by_c["series_group"] == "main") & (by_c["horizon"] == 1)]
    for m in models[2:]:
        print(f"{m}: beats naive at 1 month in {(c1[f'{m}_mae'] < c1['naive_mae']).sum()} of {len(c1)} counties")

    lr = by_h[by_h["series_group"] == "low_resolution"]
    if len(lr):
        print("\nLow-resolution series (Garissa), MAE KES/kg")
        print(lr.set_index("horizon")[[f"{m}_mae" for m in models]].round(2)
              .rename(columns=lambda c: c[:-4]).to_string())
    print(f"\nWrote metrics_by_horizon.csv, metrics_by_county.csv and differences_with_intervals.csv to {REPORT_DIR}")


if __name__ == "__main__":
    main()
