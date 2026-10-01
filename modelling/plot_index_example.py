"""Plot one county's risk index against its IPC Phase 3+ share (DL-022, DL-023).

Two panels on a shared timeline (never two y-axes on one chart): the monthly
published risk index on top, IPC's Phase 3+ share at each analysis below.
Writes a portrait image for social posts and a landscape one for the README.

The default county, Marsabit, is a typical county rather than the best one:
its within-county correlation (0.68) is close to the median across the 19
validated counties (0.66; see reports/index_validation/by_county.csv).

Usage (from the repo root):
    python -m modelling.plot_index_example
    python -m modelling.plot_index_example --county KE023 --start 2019-01-01
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import PercentFormatter

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "figures"

# Reference palette, light mode (validated: CVD dE 24.7, normal-vision dE 33.6)
SURFACE, GRID = "#fcfcfb", "#e4e3df"
TEXT, TEXT_2 = "#0b0b0b", "#52514e"
INDEX_COLOR, IPC_COLOR = "#2a78d6", "#eb6834"


def _query(sql: str, params: tuple) -> pd.DataFrame:
    import psycopg
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        cur = conn.execute(sql, params)
        return pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])


def load(county: str, start: str) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    idx = _query(
        "SELECT month, risk_index, county_name FROM marts.fct_risk_index_monthly "
        "WHERE county_pcode = %s AND month >= %s ORDER BY month", (county, start))
    ipc = _query(
        "SELECT analysis_month, share_phase3plus, is_partial_county "
        "FROM marts.fct_ipc_county_analysis "
        "WHERE county_pcode = %s AND analysis_month >= %s ORDER BY analysis_month", (county, start))
    if idx.empty or ipc.empty:
        raise SystemExit(f"No index or IPC rows for {county} from {start}")
    if ipc["is_partial_county"].any():
        print(f"Note: some IPC analyses for {county} cover only part of the county.")
    idx["month"] = pd.to_datetime(idx["month"])
    idx["risk_index"] = idx["risk_index"].astype(float)
    ipc["analysis_month"] = pd.to_datetime(ipc["analysis_month"])
    ipc["share_phase3plus"] = ipc["share_phase3plus"].astype(float)
    return idx, ipc, idx["county_name"].iloc[0]


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.grid(axis="y", color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    ax.tick_params(colors=TEXT_2, labelsize=11, length=0)


def plot(idx, ipc, name, size, path, note, bottom_margin) -> None:
    fig, (top, bottom) = plt.subplots(
        2, 1, sharex=True, figsize=size, dpi=150, facecolor=SURFACE,
        gridspec_kw={"height_ratios": [1, 1], "hspace": 0.3})

    # top: monthly risk index, 0.5 = usual for this county
    _style(top)
    top.plot(idx["month"], idx["risk_index"], color=INDEX_COLOR, linewidth=2,
             solid_capstyle="round", solid_joinstyle="round")
    top.axhline(0.5, color=TEXT_2, linewidth=1)
    top.set_ylim(0, 1)
    top.set_yticks([0, 0.5, 1], ["0", "0.5\nusual", "1"])
    top.set_title("Risk index (monthly, rainfall + vegetation; 1 = most unusual)",
                  loc="left", color=TEXT, fontsize=12, pad=8)

    # bottom: IPC Phase 3+ share at each analysis
    _style(bottom)
    bottom.plot(ipc["analysis_month"], ipc["share_phase3plus"], color=IPC_COLOR,
                linewidth=2, marker="o", markersize=8, markeredgecolor=SURFACE,
                markeredgewidth=2, solid_capstyle="round")
    bottom.set_ylim(0, max(0.6, ipc["share_phase3plus"].max() * 1.15))
    bottom.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    bottom.set_title("People in IPC Phase 3+ (crisis or worse), each assessment",
                     loc="left", color=TEXT, fontsize=12, pad=8)
    bottom.xaxis.set_major_locator(mdates.YearLocator())
    bottom.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    fig.suptitle(f"{name} County: risk index and food insecurity", x=0.06, ha="left",
                 color=TEXT, fontsize=16, fontweight="bold")
    fig.text(0.06, 0.015, note, color=TEXT_2, fontsize=9.5, ha="left", va="bottom")
    fig.subplots_adjust(left=0.1, right=0.97, top=0.88, bottom=bottom_margin)
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    print(f"Wrote {path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--county", default="KE010", help="county pcode (default KE010 Marsabit)")
    ap.add_argument("--start", default="2020-01-01")
    args = ap.parse_args()

    idx, ipc, name = load(args.county, args.start)
    stat = "Within-county correlation, 19 counties, 12 IPC analyses: Spearman ρ = 0.52 (95% CI 0.20 to 0.72)."
    src = "Sources: CHIRPS rainfall and MODIS NDVI (WFP, HDX); IPC Kenya (HDX)."
    repo = "github.com/Emakhapila/kenya-food-security-risk-index"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = name.lower().replace(" ", "_")
    plot(idx, ipc, name, (7.2, 9.0), OUT_DIR / f"index_vs_ipc_{slug}_portrait.png",
         "Within-county correlation, 19 counties, 12 IPC analyses:\n"
         "Spearman ρ = 0.52 (95% CI 0.20 to 0.72).\n" + src + "\n" + repo, 0.13)
    plot(idx, ipc, name, (11, 6.2), OUT_DIR / f"index_vs_ipc_{slug}.png",
         stat + "\n" + src + " " + repo, 0.12)


if __name__ == "__main__":
    main()
