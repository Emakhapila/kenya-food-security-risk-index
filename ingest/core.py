"""Append-only raw loading into PostgreSQL (DL-005, DL-019).

Every load is recorded in raw.load_log. A file whose SHA-256 matches the
last successful load of the same source is skipped. Otherwise each row is
hashed and only rows not already stored are inserted, so unchanged history
is stored once and revised values arrive as new rows. Nothing is updated
or deleted. All data columns are stored as text; typing happens in staging.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd
import psycopg
from dotenv import load_dotenv
from psycopg import sql

META_COLUMNS = ("load_id", "row_hash")


@dataclass
class LoadResult:
    source: str
    status: str
    load_id: int | None
    rows_in_file: int | None = None
    rows_inserted: int | None = None
    message: str = ""


def connect() -> psycopg.Connection:
    load_dotenv()
    return psycopg.connect(os.environ["DATABASE_URL"])


def ensure_load_log(conn: psycopg.Connection) -> None:
    conn.execute("CREATE SCHEMA IF NOT EXISTS raw")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw.load_log (
            load_id       bigserial PRIMARY KEY,
            source        text NOT NULL,
            file_name     text NOT NULL,
            source_url    text,
            file_sha256   text NOT NULL,
            rows_in_file  integer,
            rows_inserted integer,
            status        text NOT NULL
                          CHECK (status IN ('running', 'success', 'skipped', 'failed')),
            message       text,
            started_at    timestamptz NOT NULL DEFAULT now(),
            finished_at   timestamptz
        )
    """)
    conn.commit()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_column(name: str) -> str:
    col = re.sub(r"[^0-9a-z]+", "_", str(name).strip().lower()).strip("_") or "col"
    if col[0].isdigit():
        col = f"c_{col}"
    return f"src_{col}" if col in META_COLUMNS else col


def prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Clean column names; store empty strings as NULL; everything else as text."""
    df = df.copy()
    df.columns = [clean_column(c) for c in df.columns]
    dupes = df.columns[df.columns.duplicated()].tolist()
    if dupes:
        raise ValueError(f"column names collide after cleaning: {dupes}")
    df = df.astype(object).where(df.notna(), None)
    return df.replace({"": None})


def row_hashes(df: pd.DataFrame) -> list[str]:
    """Hash each row from its non-NULL (column=value) pairs, in column-name order.

    NULLs are left out so that a source adding a new, empty column does not
    change the hash of rows that are otherwise identical.
    """
    joined = pd.Series("", index=df.index, dtype=object)
    for c in sorted(df.columns):
        present = df[c].notna()
        joined = joined.where(~present, joined + "\x1f" + c + "=" + df[c].astype(str))
    return [hashlib.sha256(s.encode("utf-8")).hexdigest() for s in joined]


def _last_success_hash(conn, source: str) -> str | None:
    row = conn.execute(
        "SELECT file_sha256 FROM raw.load_log WHERE source = %s AND status = 'success' "
        "ORDER BY load_id DESC LIMIT 1",
        (source,),
    ).fetchone()
    return row[0] if row else None


def _ensure_table(conn, table: str, columns: list[str]) -> tuple[bool, list[str]]:
    """Create raw.<table> if needed and add any new columns. Returns (created, added)."""
    created = conn.execute(
        "SELECT to_regclass(%s) IS NULL", (f"raw.{table}",)
    ).fetchone()[0]
    conn.execute(sql.SQL(
        "CREATE TABLE IF NOT EXISTS raw.{} ("
        "load_id bigint NOT NULL REFERENCES raw.load_log (load_id), "
        "row_hash text NOT NULL UNIQUE)"
    ).format(sql.Identifier(table)))
    existing = {r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'raw' AND table_name = %s",
        (table,),
    )}
    added = [c for c in columns if c not in existing]
    for c in added:
        conn.execute(sql.SQL("ALTER TABLE raw.{} ADD COLUMN {} text").format(
            sql.Identifier(table), sql.Identifier(c)))
    return created, added


def load_file(
    conn: psycopg.Connection,
    source: str,
    path: Path,
    source_url: str,
    reader: Callable[[Path], pd.DataFrame],
) -> LoadResult:
    """Load one file into raw.<source>. Safe to re-run."""
    digest = file_sha256(path)

    if digest == _last_success_hash(conn, source):
        load_id = conn.execute(
            "INSERT INTO raw.load_log (source, file_name, source_url, file_sha256, status, "
            "message, finished_at) VALUES (%s, %s, %s, %s, 'skipped', "
            "'file unchanged since last successful load', now()) RETURNING load_id",
            (source, path.name, source_url, digest),
        ).fetchone()[0]
        conn.commit()
        return LoadResult(source, "skipped", load_id, message="file unchanged")

    load_id = conn.execute(
        "INSERT INTO raw.load_log (source, file_name, source_url, file_sha256, status) "
        "VALUES (%s, %s, %s, %s, 'running') RETURNING load_id",
        (source, path.name, source_url, digest),
    ).fetchone()[0]
    conn.commit()   # the log row survives even if the load fails

    try:
        df = prepare_frame(reader(path))
        cols = list(df.columns)
        created, added = _ensure_table(conn, source, cols)

        conn.execute(sql.SQL(
            "CREATE TEMP TABLE tmp_load (LIKE raw.{}) ON COMMIT DROP"
        ).format(sql.Identifier(source)))
        target_cols = ["load_id", "row_hash", *cols]
        col_list = sql.SQL(", ").join(map(sql.Identifier, target_cols))

        with conn.cursor() as cur:
            with cur.copy(sql.SQL("COPY tmp_load ({}) FROM STDIN").format(col_list)) as copy:
                for h, values in zip(row_hashes(df), df.itertuples(index=False, name=None)):
                    copy.write_row((load_id, h, *values))
            cur.execute(sql.SQL(
                "INSERT INTO raw.{} ({cols}) SELECT {cols} FROM tmp_load "
                "ON CONFLICT (row_hash) DO NOTHING"
            ).format(sql.Identifier(source), cols=col_list))
            inserted = cur.rowcount

        if created:
            message = f"created raw.{source} with {len(cols)} columns"
        elif added:
            message = f"new columns in source: {added}"
        else:
            message = ""
        conn.execute(
            "UPDATE raw.load_log SET status = 'success', rows_in_file = %s, "
            "rows_inserted = %s, message = %s, finished_at = now() WHERE load_id = %s",
            (len(df), inserted, message, load_id),
        )
        conn.commit()
        return LoadResult(source, "success", load_id, len(df), inserted, message)

    except Exception as exc:
        conn.rollback()
        conn.execute(
            "UPDATE raw.load_log SET status = 'failed', message = %s, finished_at = now() "
            "WHERE load_id = %s",
            (f"{type(exc).__name__}: {exc}"[:2000], load_id),
        )
        conn.commit()
        raise
