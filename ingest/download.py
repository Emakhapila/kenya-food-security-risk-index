"""Download the HDX sources into data/raw/ (FPMA stays a manual export, DL-016).

Each source names an HDX dataset and the file it needs. The file's current
download link is looked up through HDX's CKAN API (package_show), so a link that
HDX moves does not break the pipeline; only a renamed file does, and then the
error lists every file the dataset has.

Files are written to a temporary name and renamed when complete, so a failed
download never leaves a half-written file for ingestion to load. Unchanged files
are still downloaded; ingestion skips them by SHA-256 (DL-019).

Usage (from the repo root):
    python -m ingest.download                       # all HDX sources
    python -m ingest.download --source rainfall
    python -m ingest.download --list rainfall       # show the dataset's files
"""
from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path

import requests

from .sources import RAW_DOWNLOAD, SOURCES, Source

HDX_API = "https://data.humdata.org/api/3/action/package_show"
HEADERS = {"User-Agent": "kenya-food-security-risk-index (github.com/Emakhapila)"}
TIMEOUT = 120


def resources(dataset: str) -> list[dict]:
    r = requests.get(HDX_API, params={"id": dataset}, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    body = r.json()
    if not body.get("success"):
        raise RuntimeError(f"HDX package_show failed for {dataset}: {body.get('error')}")
    return body["result"]["resources"]


def _file_name(res: dict) -> str:
    return res.get("url", "").rstrip("/").split("/")[-1].split("?")[0]


def find_resource(src: Source) -> dict:
    found = [res for res in resources(src.hdx_dataset)
             if fnmatch.fnmatch(res.get("name", ""), src.pattern)
             or fnmatch.fnmatch(_file_name(res), src.pattern)]
    if len(found) != 1:
        names = sorted({res.get("name", "") for res in resources(src.hdx_dataset)})
        raise RuntimeError(
            f"{src.name}: expected 1 file matching {src.pattern!r} in HDX dataset "
            f"{src.hdx_dataset!r}, found {len(found)}. Files in the dataset: {names}")
    return found[0]


def download(src: Source) -> Path:
    res = find_resource(src)
    RAW_DOWNLOAD.mkdir(parents=True, exist_ok=True)
    target = RAW_DOWNLOAD / src.pattern
    tmp = target.with_suffix(target.suffix + ".part")
    try:
        with requests.get(res["url"], headers=HEADERS, timeout=TIMEOUT, stream=True) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
        if tmp.stat().st_size == 0:
            raise RuntimeError(f"{src.name}: downloaded file is empty ({res['url']})")
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    return target


def main(argv: list[str] | None = None) -> int:
    hdx = [s for s in SOURCES if s.hdx_dataset]
    names = [s.name for s in hdx]
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=names, action="append", help="download only this source")
    ap.add_argument("--list", choices=names, help="list the files in this source's HDX dataset")
    args = ap.parse_args(argv)

    if args.list:
        src = next(s for s in hdx if s.name == args.list)
        for res in resources(src.hdx_dataset):
            print(f"{res.get('name', ''):45s} {res.get('last_modified', '')[:10]}  {_file_name(res)}")
        return 0

    failures = 0
    for src in [s for s in hdx if not args.source or s.name in args.source]:
        try:
            path = download(src)
            print(f"{src.name:11s} downloaded  {path.name} ({path.stat().st_size / 1e6:.1f} MB)")
        except Exception as exc:
            failures += 1
            print(f"{src.name:11s} FAILED      {type(exc).__name__}: {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
