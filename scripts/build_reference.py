"""Build reference seeds: dim_county and county_alias.

dim_county   47 counties from the OCHA COD-AB gazetteer, with 2019 census
             population from OCHA COD-PS (original source: KNBS).
county_alias Every county-like name used by each raw source, mapped to an
             official county pcode. Names that match after normalisation are
             mapped automatically; known exceptions come from MANUAL; IPC
             sub-county areas are mapped by rule. The script stops if any
             source name is left unmapped.

Run from the repo root:  python scripts/build_reference.py
"""
from pathlib import Path
import re

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw_manual"
OUT = ROOT / "dbt" / "seeds"

BOUNDARIES = RAW / "ken_adminboundaries_tabulardata.xlsx"
POPULATION = RAW / "ken_admpop_2019.xlsx"
WFP_PRICES = RAW / "wfp_food_prices_ken.csv"
FPMA = RAW / "fpma_ken_maize_white_retail_2026-09-24.csv"   # update after each export
IPC = RAW / "ipc_ken_area_long.csv"

# (source, raw name) -> (official county name, include, note)
MANUAL = {
    ("wfp_prices", "Ijara"): ("Garissa", True, "former district; now a Garissa sub-county"),
    ("wfp_prices", "Meru North"): ("Meru", True, "former district"),
    ("wfp_prices", "Meru South"): ("Tharaka-Nithi", True, "former district; now in Tharaka-Nithi, not Meru"),
    ("wfp_prices", "Moyale"): ("Marsabit", True, "Kenyan Moyale is in Marsabit County"),
    ("fpma", "Embu-Mbeere"): ("Embu", True, "Mbeere, the drier eastern part of Embu"),
    ("ipc", "Taita"): ("Taita Taveta", True, "abbreviated name"),
    ("ipc", "Tharaka"): ("Tharaka-Nithi", True, "IPC area covers part of the county"),
    ("ipc", "Dadaab"): ("Garissa", False, "refugee camp; excluded (DL-015, DL-018)"),
    ("ipc", "Kakuma"): ("Turkana", False, "refugee camp; excluded (DL-015, DL-018)"),
    ("ipc", "Kalobeyei"): ("Turkana", False, "refugee settlement; excluded (DL-015, DL-018)"),
}

# IPC split these counties into sub-county areas in the 2024-07 analysis
IPC_SUBCOUNTY_PARENTS = ["Marsabit", "Turkana"]


def name_key(name: str) -> str:
    """Normalise a place name: lowercase, letters only, no trailing 'county'."""
    key = re.sub(r"[^a-z]", "", str(name).lower())
    return re.sub(r"county$", "", key)


def build_dim_county() -> pd.DataFrame:
    adm1 = pd.read_excel(BOUNDARIES, sheet_name="ADM1")
    pop = pd.read_excel(POPULATION, sheet_name="ken_admpop_ADM1_2019")

    dim = adm1[["ADM1_PCODE", "ADM1_EN", "AREA_SQKM"]].merge(
        pop[["ADM1_PCODE", "T_TL"]], on="ADM1_PCODE", how="left", validate="one_to_one"
    )
    dim.columns = ["county_pcode", "county_name", "area_sqkm", "population_2019"]
    dim.insert(1, "county_code", dim["county_pcode"].str[2:].astype(int))
    dim["area_sqkm"] = dim["area_sqkm"].round(1)

    assert len(dim) == 47, f"expected 47 counties, got {len(dim)}"
    assert dim["county_pcode"].is_unique, "duplicate county pcodes"
    assert dim["population_2019"].notna().all(), "county missing population"
    dim["population_2019"] = dim["population_2019"].astype("int64")
    return dim.sort_values("county_code").reset_index(drop=True)


def source_names() -> dict:
    prices = pd.read_csv(WFP_PRICES, usecols=["admin2"], low_memory=False)
    fpma_cols = pd.read_csv(FPMA, nrows=0).columns
    ipc = pd.read_csv(IPC, usecols=["Area"])

    def clean(values):
        names = {str(v).strip() for v in values if pd.notna(v)}
        return sorted(n for n in names if n and not n.startswith("#"))  # skip HXL tags

    return {
        "wfp_prices": clean(prices["admin2"]),
        "fpma": clean(c.split(", ")[2] for c in fpma_cols if c.count(", ") >= 3),
        "ipc": clean(ipc["Area"]),
    }


def build_county_alias(dim: pd.DataFrame) -> pd.DataFrame:
    pcode_by_key = dict(zip(dim["county_name"].map(name_key), dim["county_pcode"]))

    def resolve(county_name: str) -> str:
        key = name_key(county_name)
        if key not in pcode_by_key:
            raise SystemExit(f"'{county_name}' is not an official county name")
        return pcode_by_key[key]

    rows, unmapped = [], []
    for source, names in source_names().items():
        for raw in names:
            key = name_key(raw)
            if (source, raw) in MANUAL:
                county, include, note = MANUAL[(source, raw)]
                pcode, method = resolve(county), "manual"
            elif key in pcode_by_key:
                pcode, include, note, method = pcode_by_key[key], True, "", "auto"
            else:
                parent = next(
                    (p for p in IPC_SUBCOUNTY_PARENTS if key.startswith(name_key(p))), None
                )
                if source == "ipc" and parent:
                    pcode, include, method = resolve(parent), True, "rule"
                    note = "sub-county area; sum to county by population"
                else:
                    unmapped.append((source, raw))
                    continue
            rows.append({
                "source": source,
                "raw_name": raw,
                "county_pcode": pcode,
                "include": include,
                "match_method": method,
                "note": note,
            })

    if unmapped:
        raise SystemExit(f"Unmapped source names, add them to MANUAL: {unmapped}")

    alias = pd.DataFrame(rows)
    assert not alias.duplicated(["source", "raw_name"]).any(), "duplicate aliases"
    return alias


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    dim = build_dim_county()
    alias = build_county_alias(dim)

    dim.to_csv(OUT / "dim_county.csv", index=False, lineterminator="\n")
    alias.to_csv(OUT / "county_alias.csv", index=False, lineterminator="\n")

    print(f"dim_county:   {len(dim)} counties -> {OUT / 'dim_county.csv'}")
    print(f"county_alias: {len(alias)} names -> {OUT / 'county_alias.csv'}")
    print(alias.groupby(["source", "match_method"]).size().to_string())
    print("\nexcluded:", alias.loc[~alias["include"], "raw_name"].tolist())


if __name__ == "__main__":
    main()
