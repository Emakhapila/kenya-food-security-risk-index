"""Load raw sources into PostgreSQL.

Usage (from the repo root):
    python -m ingest.run                      # all sources
    python -m ingest.run --source rainfall    # one source
"""
from __future__ import annotations

import argparse
import sys
import time

from .core import connect, ensure_load_log, load_file
from .sources import SOURCES


def main(argv: list[str] | None = None) -> int:
    names = [s.name for s in SOURCES]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=names, action="append",
                        help="load only this source (can be repeated)")
    args = parser.parse_args(argv)
    selected = [s for s in SOURCES if not args.source or s.name in args.source]

    failures = 0
    with connect() as conn:
        ensure_load_log(conn)
        for src in selected:
            start = time.perf_counter()
            try:
                path = src.latest_file()
                r = load_file(conn, src.name, path, src.url, src.reader)
                took = time.perf_counter() - start
                if r.status == "skipped":
                    print(f"{src.name:11s} skipped   (load {r.load_id}: file unchanged)")
                else:
                    print(f"{src.name:11s} success   (load {r.load_id}: {r.rows_in_file} rows in file, "
                          f"{r.rows_inserted} new, {took:.1f}s) {r.message}")
            except Exception as exc:
                failures += 1
                print(f"{src.name:11s} FAILED    {type(exc).__name__}: {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
