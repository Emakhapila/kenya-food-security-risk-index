"""Source definitions: where each raw file comes from and how to read it.

For now every source is read from data/raw_manual/. Automatic downloads
for the HDX sources are added later; FPMA stays a manual export (DL-016).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_MANUAL = ROOT / "data" / "raw_manual"


def read_csv_as_text(path: Path) -> pd.DataFrame:
    """Read every value as text, exactly as written; drop an HDX HXL tag row if present."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    if len(df):
        first = df.iloc[0].astype(str)
        if first.str.startswith("#").sum() >= max(1, len(df.columns) // 2):
            df = df.iloc[1:].reset_index(drop=True)
    return df


def read_fpma(path: Path) -> pd.DataFrame:
    """FPMA exports are wide (one column per series). Reshape to long without changing values.

    Series labels are too long to be column names, and new counties would
    otherwise change the table's columns.
    """
    df = read_csv_as_text(path)
    df = df.drop(columns=[c for c in df.columns if c.lower() == "iso3_country_code"])
    long = df.melt(id_vars="Date", var_name="series", value_name="price")
    long.insert(0, "export_file", path.name)
    return long


@dataclass
class Source:
    name: str                 # also the raw table name: raw.<name>
    pattern: str              # file name or glob in data/raw_manual/
    url: str                  # where the data comes from (provenance)
    reader: Callable[[Path], pd.DataFrame] = read_csv_as_text

    def latest_file(self) -> Path:
        matches = sorted(RAW_MANUAL.glob(self.pattern))
        if not matches:
            raise FileNotFoundError(f"{self.name}: no file matching {self.pattern} in {RAW_MANUAL}")
        return matches[-1]    # names with ISO dates sort chronologically


# Check each URL against the HDX page in your browser and correct if needed.
SOURCES = [
    Source("wfp_prices", "wfp_food_prices_ken.csv",
           "https://data.humdata.org/dataset/wfp-food-prices-for-kenya"),
    Source("rainfall", "ken-rainfall-subnat-full.csv",
           "https://data.humdata.org/dataset/ken-rainfall-subnational"),
    Source("ndvi", "ken-ndvi-subnat-full.csv",
           "https://data.humdata.org/dataset/ken-ndvi-subnational"),
    Source("ipc", "ipc_ken_area_long.csv",
           "https://data.humdata.org/dataset/kenya-acute-food-insecurity-country-data"),
    Source("fpma", "fpma_ken_maize_white_retail_*.csv",
           "https://fpma.fao.org/giews/fpmat4/#/dashboard/tool/domestic", read_fpma),
]
