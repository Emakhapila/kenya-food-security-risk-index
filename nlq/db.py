"""Run checked queries read-only (DL-026, guardrail 1).

Settings are applied inside each transaction (SET TRANSACTION / SET LOCAL),
not as connection options, because Neon's pooled endpoint shares connections
between clients and does not keep session settings.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATEMENT_TIMEOUT = "5s"


def reader_url() -> str:
    """The read-only connection string. Never falls back to the owner's DATABASE_URL."""
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    url = os.environ.get("DASHBOARD_DATABASE_URL")
    if not url:
        raise RuntimeError("DASHBOARD_DATABASE_URL is not set (the read-only dashboard_reader login).")
    return url


def run_readonly(conn, sql: str, timeout: str = STATEMENT_TIMEOUT):
    """Run one query in a read-only transaction with a statement timeout.

    Returns (column names, rows). The transaction is rolled back afterwards,
    so nothing can persist even if a write somehow got through. The connection
    must be in autocommit mode, so each call starts a fresh transaction (inside
    an open one, SET TRANSACTION would fail or become a savepoint).
    """
    if not conn.autocommit:
        raise ValueError("run_readonly needs a connection opened with autocommit=True")
    with conn.transaction(force_rollback=True):
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute(f"SET LOCAL statement_timeout = '{timeout}'")
        cur = conn.execute(sql)
        columns = [c.name for c in cur.description] if cur.description else []
        return columns, cur.fetchall()


def can_write(conn) -> bool:
    """True if the current role can change any allowed mart: used to refuse owner logins."""
    from nlq.guard import ALLOWED_TABLES, SCHEMA
    for table in ALLOWED_TABLES:
        row = conn.execute(
            "select to_regclass(%s) is not null "
            "and (has_table_privilege(%s, 'INSERT') or has_table_privilege(%s, 'UPDATE') "
            "  or has_table_privilege(%s, 'DELETE') or has_table_privilege(%s, 'TRUNCATE'))",
            (f"{SCHEMA}.{table}",) * 5,
        ).fetchone()
        if row[0]:
            return True
    return False
