"""Check the guardrails against the real database (DL-026), as dashboard_reader.

1. Every reference query in nlq/evals/accuracy.yaml returns the same result
   before and after the query checker's rewrite.
2. Every attack probe in nlq/evals/attacks.yaml is stopped by the database
   layer alone (read-only role, read-only transaction, statement timeout),
   without the checker in front of it.

Uses DASHBOARD_DATABASE_URL only, and refuses to run if that login can write.

    python -m nlq.check_on_database
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import psycopg
import yaml

from nlq.db import can_write, reader_url, run_readonly
from nlq.guard import check

EVALS = Path(__file__).resolve().parent / "evals"


def _same(a, b, ordered: bool) -> bool:
    if ordered:
        return a == b
    return sorted(map(repr, a)) == sorted(map(repr, b))


def main() -> int:
    accuracy = yaml.safe_load((EVALS / "accuracy.yaml").read_text(encoding="utf-8"))["questions"]
    attacks = [q for q in yaml.safe_load((EVALS / "attacks.yaml").read_text(encoding="utf-8"))["questions"]
               if "probe_sql" in q]
    failures = 0

    with psycopg.connect(reader_url(), autocommit=True) as conn:
        user = conn.execute("select current_user").fetchone()[0]
        if can_write(conn):
            print(f"Refusing to run: '{user}' can change the marts. Use the read-only dashboard_reader login.")
            return 2
        print(f"Connected as {user} (read-only).\n")

        print("1. Reference queries: same result after the checker's rewrite?")
        for q in accuracy:
            guarded = check(q["sql"])
            if not guarded.ok:
                print(f"   {q['id']}  FAIL  checker rejected it: {guarded.reason}")
                failures += 1
                continue
            _, original = run_readonly(conn, q["sql"])
            _, rewritten = run_readonly(conn, guarded.sql)
            ok = _same(original, rewritten, q["ordered"])
            failures += not ok
            print(f"   {q['id']}  {'ok  ' if ok else 'FAIL'}  {len(original)} rows")

        print("\n2. Attack probes against the database alone (no checker): stopped?")
        for q in attacks:
            start = time.monotonic()
            try:
                run_readonly(conn, q["probe_sql"])
                print(f"   {q['id']}  FAIL  ran without error ({q['category']})")
                failures += 1
            except psycopg.Error as e:
                first_line = str(e).strip().splitlines()[0][:70]
                print(f"   {q['id']}  ok    {type(e).__name__}: {first_line} ({time.monotonic() - start:.1f}s)")

    print(f"\n{'All checks passed.' if failures == 0 else f'{failures} check(s) failed.'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
