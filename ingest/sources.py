"""Source definitions: where each raw file comes from and how to read it.

HDX sources are downloaded into data/raw/ by ingest.download. FPMA has no
API and stays a manual monthly export in data/raw_manual/ (DL-016).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_MANUAL = ROOT / "data" / "raw_manual"      # manual exports (FPMA)
RAW_DOWNLOAD = ROOT / "data" / "raw"           # written by ingest.download


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
    pattern: str              # file name (HDX) or glob (manual exports)
    url: str                  # where the data comes from (provenance)
    reader: Callable[[Path], pd.DataFrame] = read_csv_as_text
    hdx_dataset: str | None = None   # HDX dataset id; None = manual export

    @property
    def folder(self) -> Path:
        return RAW_DOWNLOAD if self.hdx_dataset else RAW_MANUAL

    def latest_file(self) -> Path:
        matches = sorted(self.folder.glob(self.pattern))
        if not matches:
            hint = " (run: python -m ingest.download)" if self.hdx_dataset else ""
            raise FileNotFoundError(f"{self.name}: no file matching {self.pattern} in {self.folder}{hint}")
        return matches[-1]    # names with ISO dates sort chronologically


def _hdx(dataset: str) -> str:
    return f"https://data.humdata.org/dataset/{dataset}"


SOURCES = [
    Source("wfp_prices", "wfp_food_prices_ken.csv", _hdx("wfp-food-prices-for-kenya"),
           hdx_dataset="wfp-food-prices-for-kenya"),
    Source("rainfall", "ken-rainfall-subnat-full.csv", _hdx("ken-rainfall-subnational"),
           hdx_dataset="ken-rainfall-subnational"),
    Source("ndvi", "ken-ndvi-subnat-full.csv", _hdx("ken-ndvi-subnational"),
           hdx_dataset="ken-ndvi-subnational"),
    Source("ipc", "ipc_ken_area_long.csv", _hdx("kenya-acute-food-insecurity-country-data"),
           hdx_dataset="kenya-acute-food-insecurity-country-data"),
    Source("fpma", "fpma_ken_maize_white_retail_*.csv",
           "https://fpma.fao.org/giews/fpmat4/#/dashboard/tool/domestic", read_fpma),
]
