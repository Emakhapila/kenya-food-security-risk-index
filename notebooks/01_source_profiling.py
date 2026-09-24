# %% [markdown]
# # 01 — Source profiling
# Look at each raw source before writing any ingestion code.
# Findings go into docs/data-sources.md; decisions go into docs/decisions.md.

# %% Setup — set the filenames to match what you downloaded
from pathlib import Path
import pandas as pd

pd.set_option("display.max_columns", 50)
pd.set_option("display.width", 200)

RAW = Path(r"C:\dev\kfsri\data\raw_manual")

FILES = {
    "prices":   RAW / "wfp_food_prices_ken.csv",
    "rainfall": RAW / "ken-rainfall-subnat-full.csv",
    "ndvi":     RAW / "ken-ndvi-subnat-full.csv",
    "ipc":      RAW / "ipc_ken_area_long.csv",
}

for name, path in FILES.items():
    print(f"{name:9s} {'OK ' if path.exists() else 'MISSING'} {path}")


# %% Loader — HDX files often have an HXL tag row (#date, #adm1...) right under the header
def load_hdx_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    first = df.iloc[0].astype(str)
    if first.str.startswith("#").sum() >= len(df.columns) // 2:
        print(f"  HXL tag row detected and dropped: {list(first[:4])} ...")
        df = df.iloc[1:].reset_index(drop=True)
    return df


def overview(df: pd.DataFrame, name: str) -> None:
    print(f"\n=== {name} === shape={df.shape}")
    print("columns:", list(df.columns))
    print(df.head(3).to_string())
    nulls = df.isna().mean().round(3)
    print("null share (non-zero only):")
    print(nulls[nulls > 0].to_string() or "  none")


# %% ---------- PRICES ----------
prices = load_hdx_csv(FILES["prices"])
overview(prices, "prices")

prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
prices["price"] = pd.to_numeric(prices["price"], errors="coerce")
print("\ndate range:", prices["date"].min().date(), "->", prices["date"].max().date())
print("unparseable dates:", prices["date"].isna().sum())

# %% Prices — rows with no location
print(prices[prices["admin2"].isna()][["market", "commodity", "pricetype"]].drop_duplicates().to_string())

# %% Prices — what kinds of rows are there?
for col in ["category", "pricetype", "unit", "currency", "priceflag"]:
    if col in prices.columns:
        print(f"\n{col}:")
        print(prices[col].value_counts().head(15).to_string())

# %% Prices — which maize commodities exist, and in what units / price types?
maize = prices[prices["commodity"].str.contains("maize", case=False, na=False)]
print(maize.groupby(["commodity", "pricetype", "unit"]).size()
      .sort_values(ascending=False).to_string())

# %% Maize — are the name variants the same product at different times?
grain = maize[~maize["commodity"].str.contains("flour", case=False)]
print(grain.groupby(["commodity", "pricetype", "unit"]).agg(
    first=("date", "min"), last=("date", "max"),
    markets=("market_id", "nunique"), rows=("price", "size")
).to_string())

# %% Maize — do the retail variants overlap in the same market and month?
g = grain[grain["pricetype"] == "Retail"].copy()
g["date"] = pd.to_datetime(g["date"])
g["month"] = g["date"].dt.to_period("M")
n_variants = g.groupby(["market_id", "month"])["commodity"].nunique()
print((n_variants > 1).sum(), "market-months with more than one retail maize variant")

# %% Maize retail — which markets span the rename?
old = set(g.loc[g["commodity"] == "Maize (white)", "market_id"])
new = set(g.loc[g["commodity"] == "Maize", "market_id"])
both = old & new
print(f"{len(old)} old, {len(new)} new, {len(both)} in both")
print(g[g["market_id"].isin(both)].groupby("market")["commodity"]
      .agg(lambda s: sorted(set(s))).to_string())

# %% Maize retail — prices in the overlap months, same market, side by side
ov = g[g["market_id"].isin(both)
       & g["month"].between(pd.Period("2020-08", "M"), pd.Period("2020-12", "M"))]
print(ov.pivot_table(index=["market", "month"], columns="commodity", values="price").to_string())

# %% Duplicates — same market/commodity/type/unit/date more than once?
key = ["market_id", "commodity_id", "pricetype", "unit", "date"]
dups = prices[prices.duplicated(key, keep=False)]
print(len(dups), "rows involved in duplicates")
print(dups.sort_values(key)[key + ["priceflag", "price"]].head(10).to_string())

# %% Maize retail — old vs new market names (IDs may have changed)
def norm(s):
    return s.str.lower().str.replace(r"\s*\(.*\)", "", regex=True).str.strip()

old_names = set(norm(g.loc[g["commodity"] == "Maize (white)", "market"]))
new_names = set(norm(g.loc[g["commodity"] == "Maize", "market"]))
print("old:", sorted(old_names))
print("new:", sorted(new_names))
print("shared by name:", sorted(old_names & new_names))

# %% Maize wholesale — which markets does each series cover?
w = grain[grain["pricetype"] == "Wholesale"]
for name in ["Maize (white)", "Maize (white, dry)", "Maize"]:
    print(f"{name}: {sorted(w.loc[w['commodity'] == name, 'market'].unique())}")

# %% Prices — pick ONE maize series to profile (edit after looking at the cell above)
MAIZE_COMMODITY = "Maize (white)"   # <- set from the output above
MAIZE_PRICETYPE = "Retail"          # <- or "Wholesale"
WINDOW_START = "2015-01-01"         # coverage measured from here to the latest date

m = maize[(maize["commodity"] == MAIZE_COMMODITY) & (maize["pricetype"] == MAIZE_PRICETYPE)].copy()
m["month"] = m["date"].dt.to_period("M")
m = m[m["date"] >= WINDOW_START]

months_in_window = pd.period_range(WINDOW_START, m["date"].max(), freq="M").size
coverage = (
    m.groupby(["admin1", "market"])["month"].nunique()
     .div(months_in_window).round(2)
     .sort_values(ascending=False)
     .rename("coverage")
)
print(f"{len(coverage)} markets; window = {months_in_window} months")
print(coverage.to_string())

# %% Wholesale — convert every series to price per kg, map markets to the five towns
w = grain[grain["pricetype"] == "Wholesale"].copy()
w["date"] = pd.to_datetime(w["date"])
w["month"] = w["date"].dt.to_period("M")
w["kg"] = w["unit"].str.extract(r"(\d+)\s*KG", expand=False).astype(float).fillna(1.0)
w["price_per_kg"] = w["price"] / w["kg"]

TOWN = {
    "Eldoret town (Uasin Gishu)": "Eldoret", "Kisumu": "Kisumu", "Mombasa": "Mombasa",
    "Nairobi": "Nairobi", "Nakuru": "Nakuru",
    "Kibuye (Kisumu)": "Kisumu", "Kongowea (Mombasa)": "Mombasa",
    "Wakulima (Nairobi)": "Nairobi", "Wakulima (Nakuru)": "Nakuru",
}
w["town"] = w["market"].map(TOWN)
wide = w[w["town"].notna()].pivot_table(
    index=["town", "month"], columns="commodity", values="price_per_kg")
print(wide.notna().groupby("town").sum().to_string())

# %% Retail — do the four renamed ASAL markets join across 2020?
g["town"] = norm(g["market"]).str.replace(r"\s+town$", "", regex=True)
four = g[g["town"].isin(["garissa", "lodwar", "marigat", "marsabit"])
         & g["commodity"].isin(["Maize (white)", "Maize"])]
rw = four.pivot_table(index=["town", "month"], columns="commodity", values="price")
print(rw.notna().groupby("town").sum().to_string())
both = rw.dropna()
pct = (both["Maize (white)"] / both["Maize"] - 1).abs() * 100
print(f"{len(both)} overlapping town-months; median diff {pct.median():.1f}%")
print(both.round(2).to_string())

# %% Retail "Maize" — months of data per market
print(g[g["commodity"] == "Maize"].groupby("market")["month"].nunique()
      .sort_values(ascending=False).to_string())

# %% Prices — how many markets clear each candidate threshold? (feeds DL-009)
for t in [0.5, 0.6, 0.7, 0.8, 0.9]:
    print(f"coverage >= {t:.0%}: {(coverage >= t).sum()} markets")


# %% Wholesale — do the series agree where they overlap?
def compare(a, b):
    both = wide[[a, b]].dropna()
    pct = (both[a] / both[b] - 1).abs() * 100
    print(f"{a} vs {b}: {len(both)} town-months, "
          f"median diff {pct.median():.1f}%, 90th pct {pct.quantile(0.9):.1f}%, max {pct.max():.1f}%")
    return both

compare("Maize (white)", "Maize")
overlap = compare("Maize", "Maize (white, dry)")
print(overlap.round(2).head(20).to_string())

# %% Prices — longest gap per market (a 90% coverage market with one 2-year hole is a problem)
def longest_gap(months: pd.Series) -> int:
    s = months.sort_values().drop_duplicates()
    gaps = s.apply(lambda p: p.ordinal).diff().fillna(1) - 1
    return int(gaps.max())

gaps = m.groupby("market")["month"].apply(longest_gap).rename("longest_gap_months")
print(pd.concat([coverage.droplevel(0), gaps], axis=1)
      .sort_values("coverage", ascending=False).head(20).to_string())

# %% Prices — how do counties appear? (feeds dim_county tomorrow)
print(prices["admin1"].value_counts().to_string())
if "admin2" in prices.columns:
    print("\nadmin2 sample:", prices["admin2"].dropna().unique()[:20])


# %% ---------- RAINFALL ----------
rain = load_hdx_csv(FILES["rainfall"])
overview(rain, "rainfall")
rain["date"] = pd.to_datetime(rain["date"], errors="coerce")
print("\ndate range:", rain["date"].min().date(), "->", rain["date"].max().date())

# %% Rainfall — admin units and codes
for col in rain.columns:
    if any(k in col.lower() for k in ["adm", "pcode", "level"]):
        print(f"{col}: {rain[col].nunique()} unique, e.g. {list(rain[col].dropna().unique()[:5])}")

# %% Rainfall — dekads per year (expect 36) and any version column
print(rain.groupby(rain["date"].dt.year)["date"].nunique().tail(10).to_string())
if "version" in rain.columns:
    print(rain["version"].value_counts().to_string())


# %% ---------- NDVI ----------
ndvi = load_hdx_csv(FILES["ndvi"])
overview(ndvi, "ndvi")
ndvi["date"] = pd.to_datetime(ndvi["date"], errors="coerce")
print("\ndate range:", ndvi["date"].min().date(), "->", ndvi["date"].max().date())

# %% NDVI — do its admin codes match rainfall's?
def code_cols(df):
    return [c for c in df.columns if "pcode" in c.lower() or c.lower().startswith("adm")]

print("rainfall code cols:", code_cols(rain))
print("ndvi code cols:    ", code_cols(ndvi))
shared = set(code_cols(rain)) & set(code_cols(ndvi))
for c in shared:
    a, b = set(rain[c].dropna()), set(ndvi[c].dropna())
    print(f"{c}: rain={len(a)} ndvi={len(b)} both={len(a & b)}")


# %% ---------- IPC ----------
ipc = load_hdx_csv(FILES["ipc"])
overview(ipc, "ipc")

# %% IPC — analysis periods, area names, phase columns
for col in ipc.columns:
    if any(k in col.lower() for k in ["date", "period", "validity", "area", "phase", "level", "adm"]):
        print(f"\n{col}: {ipc[col].nunique()} unique")
        print(ipc[col].value_counts().head(10).to_string())


# %% ---------- CROSS-SOURCE: county naming ----------
# Collect every county-like name from each source to see the mismatches dim_county must fix.
def names(df, candidates):
    for c in candidates:
        if c in df.columns:
            return set(df[c].dropna().astype(str).str.strip())
    return set()

price_counties = names(prices, ["admin1"])
rain_names = names(rain, ["adm1_name", "ADM1_EN", "adm_name", "name"])   # adjust after overview
ipc_names = names(ipc, ["Level 1", "area", "Area", "adm1_name"])         # adjust after overview

print(f"prices: {len(price_counties)} | rainfall: {len(rain_names)} | ipc: {len(ipc_names)}")
print("\nIn prices but not rainfall:", sorted(price_counties - rain_names)[:30])
print("\nIn rainfall but not prices:", sorted(rain_names - price_counties)[:30])

# %% ---------- FPMA (FEWS NET retail maize, ASAL counties) ----------
FPMA = RAW / "fpma_ken_maize_white_retail_2026-09-24.csv"   # <- match your file name
lines = FPMA.read_text(encoding="utf-8", errors="replace").splitlines()
print(f"{len(lines)} lines")
print("\n".join(lines[:12]))
print("...")
print("\n".join(lines[-3:]))

# %% FPMA — reshape from wide to long
fp = pd.read_csv(FPMA, dtype=str).drop(columns=["iso3_country_code"])
fp["date"] = pd.to_datetime(fp["Date"], format="%m/%d/%Y")
fpl = fp.drop(columns="Date").melt(id_vars="date", var_name="series", value_name="price")
fpl["county_raw"] = fpl["series"].str.split(", ").str[2]
fpl["price"] = pd.to_numeric(fpl["price"], errors="coerce")
fpl["month"] = fpl["date"].dt.to_period("M")
print(fpl.shape, "|", fpl["date"].min().date(), "->", fpl["date"].max().date())
print(sorted(fpl["county_raw"].unique()))

# %% FPMA — coverage, longest gap and longest flat run per county
def longest_flat_run(s: pd.Series) -> int:
    s = s.dropna()
    if s.empty:
        return 0
    return int(s.groupby((s != s.shift()).cumsum()).size().max())

def profile(g: pd.DataFrame) -> pd.Series:
    g = g.sort_values("month")
    have = g.dropna(subset=["price"])
    missing = g["price"].isna()
    longest_gap = int(missing.groupby((~missing).cumsum()).sum().max())
    return pd.Series({
        "months": len(have),
        "coverage": round(len(have) / len(g), 2),
        "first": have["month"].min(),
        "last": have["month"].max(),
        "longest_gap": longest_gap,
        "longest_flat_run": longest_flat_run(g["price"]),
    })

fp_profile = fpl.groupby("county_raw").apply(profile, include_groups=False)
print(fp_profile.sort_values("coverage").to_string())

# %% FPMA — which months are missing, and for which counties?
miss = (fpl[fpl["price"].isna()].groupby("month")["county_raw"]
        .agg(n="count", counties=lambda s: ", ".join(sorted(s))))
print(miss.to_string())

# %% FPMA — where are the long flat runs?
for c in ["Garissa", "Makueni", "Taita Taveta", "Wajir"]:
    d = fpl[fpl["county_raw"] == c].dropna(subset=["price"]).sort_values("month")[["month", "price"]]
    d["run"] = (d["price"] != d["price"].shift()).cumsum()
    runs = d.groupby("run").agg(value=("price", "first"), start=("month", "min"),
                                end=("month", "max"), length=("price", "size"))
    print(f"\n{c}")
    print(runs[runs["length"] >= 6].to_string(index=False))

# %% [markdown]
# ## Write up in docs/data-sources.md, one section per source:
# - URL, licence, file name, last modified
# - Grain (market-month? admin2-dekad? IPC area-period?) and date range
# - Coverage: markets passing the threshold, longest gaps
# - Identifiers: county names/codes used, mismatches found
# - Problems: units, mixed price types, missing periods, anything surprising

# %%
