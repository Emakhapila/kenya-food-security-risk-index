"""Tests for modelling/validate_index.py on synthetic data with known answers."""
import numpy as np
import pandas as pd
import pytest

from modelling import validate_index as v


def synthetic(n_counties=15, n_analyses=12, signal=1.0, seed=1):
    """County-analyses where share = county level + signal * index shock + noise.

    County levels are set to run AGAINST the county's average index, so the
    correlation without removing county means is misleading by construction.
    """
    rng = np.random.default_rng(seed)
    months = pd.date_range("2021-02-01", periods=n_analyses, freq="6MS")
    rows = []
    for c in range(n_counties):
        county_mean_index = rng.uniform(0.3, 0.7)
        county_level = 0.6 - county_mean_index           # opposite direction
        for m in months:
            shock = rng.normal(0, 0.1)
            noise_idx = rng.uniform(0, 1)
            rows.append({
                "county_pcode": f"KE{c:03d}", "county_name": f"C{c}", "analysis_month": m,
                "is_partial_county": False, "climate_source_level": "adm1" if c % 2 else "adm2_proxy",
                "share_phase3plus": county_level + signal * shock + rng.normal(0, 0.02),
                "index_v2_climate_pre3": county_mean_index + shock,
                "index_v1_rain_pre3": noise_idx,                        # no information
                "index_v3_climate_price_pre3": county_mean_index + shock if c < 8 else np.nan,
                "index_v2_climate_at_analysis": county_mean_index + shock,
                "index_v2_climate_validity": county_mean_index + shock,
            })
    return pd.DataFrame(rows)


@pytest.fixture(autouse=True)
def fewer_reps(monkeypatch):
    monkeypatch.setattr(v, "REPS", 300)


def test_within_county_recovers_signal_that_raw_correlation_hides():
    df = synthetic()
    assert v.within_county_spearman(df, "index_v2_climate_pre3") > 0.8
    assert v.within_county_spearman(df, "index_v2_climate_pre3", demean=False) < 0


def test_counties_with_too_few_analyses_are_excluded():
    df = synthetic(n_analyses=12)
    few = synthetic(n_counties=1, n_analyses=3, seed=9).assign(county_pcode="KE999")
    few["index_v2_climate_pre3"] = -few["index_v2_climate_pre3"]   # would hurt if included
    both = pd.concat([df, few])
    assert v.within_county_spearman(both, "index_v2_climate_pre3") == pytest.approx(
        v.within_county_spearman(df, "index_v2_climate_pre3"))


def test_primary_supported_with_signal_and_not_with_noise():
    strong = v.run(synthetic(signal=1.0))[0]
    assert strong.role == "primary" and strong.ci_low > 0

    null = v.correlation(synthetic(signal=1.0), "primary", "noise", "x", "index_v1_rain_pre3")
    assert null.ci_low < 0 < null.ci_high


def test_paired_difference_detects_the_informative_variant():
    d21 = v.run(synthetic())[1]
    assert d21.test.startswith("variant 2 - variant 1") and d21.ci_low > 0


def test_bootstrap_resamples_whole_analyses_and_is_reproducible():
    df = synthetic(n_analyses=6)
    # whole analyses are drawn, so every resample has n_analyses x 15 counties rows
    sizes = v.bootstrap(df, lambda d: len(d))
    assert set(sizes) == {6 * 15}
    a = v.bootstrap(df, lambda d: v.within_county_spearman(d, "index_v2_climate_pre3"))
    b = v.bootstrap(df, lambda d: v.within_county_spearman(d, "index_v2_climate_pre3"))
    assert np.array_equal(a, b)


def test_matches_scipy_spearman_on_pandas_demeaned_data():
    from scipy.stats import spearmanr
    df = synthetic()
    d = df[["county_pcode", "index_v2_climate_pre3", "share_phase3plus"]].copy()
    for c in ("index_v2_climate_pre3", "share_phase3plus"):
        d[c] = d[c] - d.groupby("county_pcode")[c].transform("mean")
    expected = spearmanr(d["index_v2_climate_pre3"], d["share_phase3plus"])[0]
    assert v.within_county_spearman(df, "index_v2_climate_pre3") == pytest.approx(expected)
