"""Check the guardrails against the real database (DL-026), as the read-only role.

0. The columns documented in dbt/models/marts/_marts.yml (what the model is
   told) are exactly the columns in the database.
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
from nlq.guard import ALLOWED_TABLES, SCHEMA, check
from nlq.prompt import MARTS_YML

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
            print(f"Refusing to run: '{user}' can change the marts. Use a read-only login (DL-012).")
            return 2
        print(f"Connected as {user} (read-only).\n")

        print("0. Documented columns (what the model is told) = columns in the database?")
        documented = {m["name"]: {c["name"] for c in m.get("columns", [])}
                      for m in yaml.safe_load(MARTS_YML.read_text(encoding="utf-8"))["models"]}
        for table in sorted(ALLOWED_TABLES):
            actual = {r[0] for r in conn.execute(
                "select column_name from information_schema.columns "
                "where table_schema = %s and table_name = %s", (SCHEMA, table)).fetchall()}
            missing, extra = actual - documented.get(table, set()), documented.get(table, set()) - actual
            ok = actual and not missing and not extra
            failures += not ok
            detail = "" if ok else f"  undocumented: {sorted(missing)}  not in database: {sorted(extra)}"
            print(f"   {table:<28} {'ok  ' if ok else 'FAIL'}{detail}")
        print()

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
