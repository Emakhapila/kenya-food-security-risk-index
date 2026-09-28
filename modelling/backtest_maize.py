"""Rolling-origin backtest of retail maize price forecasts (DL-010, DL-016).

Models, all forecasting log price 1-3 months ahead from the same information:
  naive           last observed price
  seasonal_naive  price in the same month one year earlier
  sarimax         per-county SARIMAX(1,1,1)(1,0,0,12) on log price, refit at every origin
  lightgbm        one global model per horizon across all counties, predicting the
                  log change from the origin month (not the price level, because
                  trees cannot extrapolate beyond prices seen in training)

At each origin only data up to and including the origin month is used, and
LightGBM is trained only on rows whose target month is on or before the origin.
Errors are measured on the price scale (KES/kg). Low-resolution series
(Garissa, DL-016) are reported separately.

Usage (from the repo root):
    python -m modelling.backtest_maize                  # reads marts.fct_maize_price_monthly
    python -m modelling.backtest_maize --test-months 24 --csv path/to/export.csv
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
SARIMAX_ORDER = (1, 1, 1)
SARIMAX_SEASONAL = (1, 0, 0, 12)
LGB_PARAMS = dict(
    n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20,
    subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
    random_state=42, verbose=-1,
)


# ---------------------------------------------------------------- data

def load_prices(csv: str | None) -> pd.DataFrame:
    cols = ["county_pcode", "county_name", "month", "price_kes_per_kg", "is_low_resolution"]
    if csv:
        df = pd.read_csv(csv, usecols=cols)
    else:
        import psycopg
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            cur = conn.execute(f"SELECT {', '.join(cols)} FROM marts.fct_maize_price_monthly")
            df = pd.DataFrame(cur.fetchall(), columns=cols)
    df["month"] = pd.to_datetime(df["month"])
    df["price_kes_per_kg"] = pd.to_numeric(df["price_kes_per_kg"], errors="coerce").astype(float)
    df["is_low_resolution"] = df["is_low_resolution"].astype(str).str.lower().isin(["true", "t", "1"])
    return df


def to_wide(df: pd.DataFrame) -> pd.DataFrame:
    """Months x counties of log price, on a complete monthly index."""
    wide = df.pivot(index="month", columns="county_pcode", values="price_kes_per_kg")
    wide = wide.asfreq("MS")
    return np.log(wide)


# ---------------------------------------------------------------- features for LightGBM

def build_features(y: pd.DataFrame) -> pd.DataFrame:
    """Long frame of features known at month t, one row per county and month."""
    r1 = y.diff(1)
    frames = {
        "r1": r1,
        "r3": y.diff(3),
        "r6": y.diff(6),
        "r12": y.diff(12),
        "dev12": y - y.rolling(12, min_periods=6).mean(),
        "vol6": r1.rolling(6, min_periods=3).std(),
        "rel_level": y.sub(y.mean(axis=1), axis=0),
    }
    nat = {
        "nat_r1": r1.mean(axis=1),
        "nat_r3": y.diff(3).mean(axis=1),
    }
    long = pd.concat({k: v.stack(future_stack=True) for k, v in frames.items()}, axis=1)
    long.index.names = ["month", "county_pcode"]
    long = long.reset_index()
    for k, v in nat.items():
        long[k] = long["month"].map(v)
    long["y"] = y.stack(future_stack=True).values
    long["county"] = long["county_pcode"].astype("category")
    return long


FEATURES = ["r1", "r3", "r6", "r12", "dev12", "vol6", "rel_level",
            "nat_r1", "nat_r3", "target_month", "county"]


def lightgbm_forecasts(y: pd.DataFrame, feats: pd.DataFrame, origin: pd.Timestamp) -> dict:
    """Return {(county, h): forecast log price} for one origin."""
    out = {}
    at_origin = feats[(feats["month"] == origin) & feats["y"].notna()]
    for h in HORIZONS:
        f = feats.copy()
        target_level = y.shift(-h).stack(future_stack=True)
        f["target"] = target_level.values - f["y"].values
        f["target_month"] = (f["month"] + pd.DateOffset(months=h)).dt.month
        train = f[(f["month"] + pd.DateOffset(months=h) <= origin) & f["target"].notna()]
        model = lgb.LGBMRegressor(**LGB_PARAMS)
        model.fit(train[FEATURES], train["target"], categorical_feature=["county"])
        x = at_origin.copy()
        x["target_month"] = (origin + pd.DateOffset(months=h)).month
        pred = model.predict(x[FEATURES])
        for c, base, p in zip(x["county_pcode"], x["y"], pred):
            out[(c, h)] = base + p
    return out


# ---------------------------------------------------------------- other models

def last_observed(s: pd.Series, origin: pd.Timestamp) -> float:
    s = s.loc[:origin].dropna()
    return s.iloc[-1] if len(s) else np.nan


def sarimax_forecasts(s: pd.Series, origin: pd.Timestamp) -> dict:
    train = s.loc[:origin]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        warnings.simplefilter("ignore", UserWarning)
        res = SARIMAX(train, order=SARIMAX_ORDER, seasonal_order=SARIMAX_SEASONAL,
                      enforce_stationarity=False, enforce_invertibility=False
                      ).fit(disp=False, maxiter=200)
    fc = res.forecast(steps=max(HORIZONS))
    return {h: float(fc.iloc[h - 1]) for h in HORIZONS}


# ---------------------------------------------------------------- backtest

def run_backtest(y: pd.DataFrame, test_months: int) -> pd.DataFrame:
    last = y.index.max()
    origins = pd.date_range(last - pd.DateOffset(months=test_months), last - pd.DateOffset(months=1), freq="MS")
    feats = build_features(y)
    rows = []
    for i, origin in enumerate(origins, 1):
        t0 = time.perf_counter()
        lgb_fc = lightgbm_forecasts(y, feats, origin)
        for c in y.columns:
            s = y[c]
            base = last_observed(s, origin)
            try:
                sar = sarimax_forecasts(s, origin)
            except Exception:                       # rare numerical failure: record as missing
                sar = {h: np.nan for h in HORIZONS}
            for h in HORIZONS:
                target = origin + pd.DateOffset(months=h)
                if target > last:
                    continue
                seasonal = s.get(target - pd.DateOffset(months=12), np.nan)
                rows.append({
                    "origin": origin, "target_month": target, "horizon": h, "county_pcode": c,
                    "actual": s.get(target, np.nan),
                    "naive": base,
                    "seasonal_naive": seasonal,
                    "sarimax": sar[h],
                    "lightgbm": lgb_fc.get((c, h), base),   # fall back to naive if origin missing
                })
        print(f"  origin {origin:%Y-%m} ({i}/{len(origins)}) {time.perf_counter() - t0:.1f}s", flush=True)
    fc = pd.DataFrame(rows)
    for col in ["actual", "naive", "seasonal_naive", "sarimax", "lightgbm"]:
        fc[col] = np.exp(fc[col])                    # back to KES/kg
    return fc


MODELS = ["naive", "seasonal_naive", "sarimax", "lightgbm"]


def score(fc: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    fc = fc.dropna(subset=["actual"])
    out = []
    for keys, g in fc.groupby(by):
        keys = keys if isinstance(keys, tuple) else (keys,)
        row = dict(zip(by, keys))
        row["n"] = len(g)
        for m in MODELS:
            err = (g[m] - g["actual"]).abs()
            row[f"{m}_mae"] = err.mean()
            row[f"{m}_mape"] = (err / g["actual"]).mean() * 100
        for m in ["sarimax", "lightgbm"]:
            row[f"{m}_skill_vs_naive"] = 1 - row[f"{m}_mae"] / row["naive_mae"]
        out.append(row)
    return pd.DataFrame(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--test-months", type=int, default=24)
    ap.add_argument("--csv", help="read prices from a CSV export instead of the database")
    args = ap.parse_args()

    df = load_prices(args.csv)
    names = df.drop_duplicates("county_pcode").set_index("county_pcode")["county_name"]
    low_res = set(df.loc[df["is_low_resolution"], "county_pcode"])
    y = to_wide(df)
    print(f"{y.shape[1]} counties, {y.index.min():%Y-%m} to {y.index.max():%Y-%m}; "
          f"testing the last {args.test_months} origins")

    fc = run_backtest(y, args.test_months)
    fc["county_name"] = fc["county_pcode"].map(names)
    fc["series_group"] = np.where(fc["county_pcode"].isin(low_res), "low_resolution", "main")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    FORECAST_DIR.mkdir(parents=True, exist_ok=True)
    fc.to_csv(FORECAST_DIR / "backtest_forecasts.csv", index=False)
    by_h = score(fc, ["series_group", "horizon"])
    by_c = score(fc, ["series_group", "county_name", "horizon"])
    by_h.round(3).to_csv(REPORT_DIR / "metrics_by_horizon.csv", index=False)
    by_c.round(3).to_csv(REPORT_DIR / "metrics_by_county.csv", index=False)

    main_h = by_h[by_h["series_group"] == "main"].set_index("horizon")
    print("\nMAE, KES per kg (main series; lower is better)")
    print(main_h[[f"{m}_mae" for m in MODELS]].round(2).to_string())
    print("\nMAPE, % (main series)")
    print(main_h[[f"{m}_mape" for m in MODELS]].round(1).to_string())
    print("\nSkill vs naive (1 - MAE/naive MAE; above 0 means better than naive)")
    print(main_h[["sarimax_skill_vs_naive", "lightgbm_skill_vs_naive"]].round(3).to_string())

    c1 = by_c[(by_c["series_group"] == "main") & (by_c["horizon"] == 1)]
    for m in ["sarimax", "lightgbm"]:
        wins = (c1[f"{m}_mae"] < c1["naive_mae"]).sum()
        print(f"{m}: beats naive at 1 month in {wins} of {len(c1)} counties")

    lr = by_h[by_h["series_group"] == "low_resolution"]
    if len(lr):
        print("\nLow-resolution series (Garissa), MAE KES/kg")
        print(lr.set_index("horizon")[[f"{m}_mae" for m in MODELS]].round(2).to_string())
    print(f"\nWrote {REPORT_DIR / 'metrics_by_horizon.csv'} and metrics_by_county.csv")


if __name__ == "__main__":
    main()
