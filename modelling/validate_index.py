"""Validate the county risk index against IPC, exactly as pre-registered in DL-022.

Reads marts.fct_risk_index_ipc (one row per county-analysis, DL-018/DL-022).

Primary test
    Spearman correlation between the index (variant 2: rainfall + vegetation) and
    the IPC Phase 3+ share, after subtracting each county's own mean from both
    (within-county). Index = mean over the 3 months before the analysis month.
    Sample: whole-county IPC areas, counties with at least 4 analyses.
    Claim supported if the correlation is positive and its 95% interval excludes 0.

Comparisons (paired, same rows for both variants)
    variant 2 - variant 1   does vegetation add to rainfall?
    variant 3 - variant 2   does price add? (16 FEWS NET counties)
    A component adds information only if the interval of the difference excludes 0.

Context and sensitivity (reported, never used for the claims)
    correlation without removing county means; partial-county IPC areas;
    adm1 vs adm2-proxy climate counties; index at the analysis month; index over
    the IPC validity window.

Intervals: bootstrap over IPC analyses (not rows: counties in one analysis share
conditions), 2,000 resamples, percentile 95%. The whole statistic, including the
county de-meaning and the 4-analysis rule, is recomputed on every resample.

Usage (from the repo root):
    python -m modelling.validate_index
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "index_validation"
MIN_ANALYSES = 4                 # DL-022: counties need at least this many analyses
REPS = 2000
SEED = 0
TARGET = "share_phase3plus"
V1, V2, V3 = "index_v1_rain", "index_v2_climate", "index_v3_climate_price"


# ---------------------------------------------------------------- statistics

def within_county_spearman(df: pd.DataFrame, x: str, y: str = TARGET,
                           demean: bool = True) -> float:
    """Spearman correlation of x and y after removing each county's mean.

    Rows with a missing x or y are dropped, then counties with fewer than
    MIN_ANALYSES rows, then the county means are removed.
    """
    xv = df[x].to_numpy(dtype=float)
    yv = df[y].to_numpy(dtype=float)
    ok = ~(np.isnan(xv) | np.isnan(yv))
    xv, yv = xv[ok], yv[ok]
    _, county = np.unique(df["county_pcode"].to_numpy()[ok], return_inverse=True)
    counts = np.bincount(county)
    keep = counts[county] >= MIN_ANALYSES
    xv, yv, county = xv[keep], yv[keep], county[keep]
    if len(xv) < 3:
        return np.nan
    if demean:
        n = np.bincount(county)
        xv = xv - (np.bincount(county, xv) / np.maximum(n, 1))[county]
        yv = yv - (np.bincount(county, yv) / np.maximum(n, 1))[county]
    rx, ry = rankdata(xv), rankdata(yv)
    if rx.std() == 0 or ry.std() == 0:
        return np.nan
    return float(np.corrcoef(rx, ry)[0, 1])


def bootstrap(df: pd.DataFrame, stat, reps: int | None = None, seed: int = SEED) -> np.ndarray:
    """Recompute stat(resampled df) over resamples of whole IPC analyses."""
    reps = REPS if reps is None else reps
    rng = np.random.default_rng(seed)
    if df.empty:
        return np.full(reps, np.nan)
    df = df.reset_index(drop=True)
    groups = [idx for idx in df.groupby("analysis_month").indices.values()]
    out = np.empty(reps)
    for i in range(reps):
        pick = rng.choice(len(groups), size=len(groups), replace=True)
        out[i] = stat(df.iloc[np.concatenate([groups[j] for j in pick])])
    return out


@dataclass
class Result:
    role: str            # primary | comparison | variant | context | sensitivity
    test: str
    sample: str
    estimate: float
    ci_low: float
    ci_high: float
    n_rows: int
    n_counties: int
    n_analyses: int

    @property
    def excludes_zero(self) -> bool:
        return bool(self.ci_low > 0 or self.ci_high < 0)


def _size(df: pd.DataFrame, cols: list[str]) -> tuple[int, int, int]:
    d = df.dropna(subset=cols)
    d = d[d.groupby("county_pcode")[cols[0]].transform("size") >= MIN_ANALYSES]
    return len(d), d["county_pcode"].nunique(), d["analysis_month"].nunique()


def _interval(boots: np.ndarray) -> tuple[float, float]:
    if np.isnan(boots).all():
        return np.nan, np.nan
    lo, hi = np.nanpercentile(boots, [2.5, 97.5])
    return float(lo), float(hi)


def correlation(df, role, test, sample, x, demean=True) -> Result:
    est = within_county_spearman(df, x, demean=demean)
    lo, hi = _interval(bootstrap(df, lambda d: within_county_spearman(d, x, demean=demean)))
    return Result(role, test, sample, est, lo, hi, *_size(df, [x, TARGET]))


def difference(df, test, sample, a, b) -> Result:
    """corr(a) - corr(b), both on the rows where a and b are both present."""
    d = df.dropna(subset=[a, b])
    f = lambda s: within_county_spearman(s, a) - within_county_spearman(s, b)
    lo, hi = _interval(bootstrap(d, f))
    return Result("comparison", test, sample, f(d), lo, hi, *_size(d, [a, b, TARGET]))


# ---------------------------------------------------------------- run

def run(df: pd.DataFrame) -> list[Result]:
    whole = df[~df["is_partial_county"]]
    partial = df[df["is_partial_county"]]
    pre = lambda v: f"{v}_pre3"
    res = [
        correlation(whole, "primary", "variant 2 (rain + NDVI), within-county",
                    "whole-county", pre(V2)),
        difference(whole, "variant 2 - variant 1 (does NDVI add?)", "whole-county",
                   pre(V2), pre(V1)),
        difference(whole, "variant 3 - variant 2 (does price add?)",
                   "whole-county, FEWS NET counties", pre(V3), pre(V2)),
        correlation(whole, "variant", "variant 1 (rain), within-county", "whole-county", pre(V1)),
        correlation(whole, "variant", "variant 3 (rain + NDVI + price), within-county",
                    "whole-county, FEWS NET counties", pre(V3)),
        correlation(whole, "context", "variant 2, county means NOT removed", "whole-county",
                    pre(V2), demean=False),
        correlation(partial, "context", "variant 2, within-county", "partial-county areas", pre(V2)),
    ]
    for level in ("adm1", "adm2_proxy"):
        res.append(correlation(whole[whole["climate_source_level"] == level], "context",
                               "variant 2, within-county", f"whole-county, {level} climate", pre(V2)))
    res += [
        correlation(whole, "sensitivity", "variant 2 at the analysis month", "whole-county",
                    f"{V2}_at_analysis"),
        correlation(whole, "sensitivity", "variant 2 over the validity window", "whole-county",
                    f"{V2}_validity"),
    ]
    return res


def by_county(df: pd.DataFrame) -> pd.DataFrame:
    """Per-county correlations (few points each; descriptive only)."""
    whole = df[~df["is_partial_county"]].dropna(subset=[f"{V2}_pre3", TARGET])
    rows = []
    for (c, name), g in whole.groupby(["county_pcode", "county_name"]):
        rho = g[f"{V2}_pre3"].rank().corr(g[TARGET].rank()) if len(g) >= MIN_ANALYSES else np.nan
        rows.append({"county_pcode": c, "county_name": name, "n_analyses": len(g),
                     "climate_source_level": g["climate_source_level"].iloc[0],
                     "mean_share_phase3plus": g[TARGET].mean(), "spearman_v2": rho})
    return pd.DataFrame(rows).sort_values("county_name")


def load() -> pd.DataFrame:
    import psycopg
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        cur = conn.execute("SELECT * FROM marts.fct_risk_index_ipc")
        df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
    df["analysis_month"] = pd.to_datetime(df["analysis_month"])
    for c in df.columns:
        if c.startswith("index_") or c == TARGET:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    df["is_partial_county"] = df["is_partial_county"].astype(bool)
    return df


def main() -> None:
    argparse.ArgumentParser(description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    df = load()
    results = run(df)
    table = pd.DataFrame([{**r.__dict__, "ci_excludes_zero": r.excludes_zero} for r in results])

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    table.round(3).to_csv(REPORT_DIR / "validation_results.csv", index=False)
    by_county(df).round(3).to_csv(REPORT_DIR / "by_county.csv", index=False)

    pd.set_option("display.width", 200)
    print(f"IPC analyses: {df['analysis_month'].nunique()}  county-analyses: {len(df)}  "
          f"bootstrap: {REPS} resamples of analyses\n")
    print(table[["role", "test", "sample", "estimate", "ci_low", "ci_high",
                 "n_rows", "n_counties", "n_analyses"]].round(3).to_string(index=False))

    p, d21, d32 = results[0], results[1], results[2]
    print("\nPre-registered claims (DL-022):")
    verdict = ("NOT TESTABLE (sample too small)" if np.isnan(p.ci_low)
               else "SUPPORTED" if p.estimate > 0 and p.ci_low > 0 else "NOT SUPPORTED")
    print(f"  Index tracks IPC within counties: {verdict} "
          f"(rho {p.estimate:.3f}, 95% CI {p.ci_low:.3f} to {p.ci_high:.3f})")
    for r, what in ((d21, "NDVI adds to rainfall"), (d32, "Price adds to climate")):
        verdict = ("NOT TESTABLE (sample too small)" if np.isnan(r.ci_low)
                   else "YES" if r.ci_low > 0 else "NO (worse)" if r.ci_high < 0
                   else "NOT SHOWN (interval includes 0)")
        print(f"  {what}: {verdict} (difference {r.estimate:+.3f}, 95% CI {r.ci_low:+.3f} to {r.ci_high:+.3f})")
    print(f"\nOnly {df['analysis_month'].nunique()} analyses: intervals are wide by design (DL-022).")
    print(f"Wrote validation_results.csv and by_county.csv to {REPORT_DIR}")


if __name__ == "__main__":
    main()
