"""Tests for the read-only runner (DL-026, guardrail 1), with a fake connection."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from nlq import db


class FakeConnection:
    def __init__(self, autocommit=True):
        self.autocommit = autocommit
        self.calls = []
        self.rolled_back = None

    @contextmanager
    def transaction(self, force_rollback=False):
        self.calls.append("BEGIN")
        yield
        self.rolled_back = force_rollback

    def execute(self, sql, params=None):
        self.calls.append(sql)
        return SimpleNamespace(description=[SimpleNamespace(name="x")], fetchall=lambda: [(1,)])


def test_query_runs_inside_a_read_only_transaction_with_a_timeout_and_is_rolled_back():
    conn = FakeConnection()
    columns, rows = db.run_readonly(conn, "SELECT 1")
    assert conn.calls == ["BEGIN", "SET TRANSACTION READ ONLY",
                          "SET LOCAL statement_timeout = '5s'", "SELECT 1"]
    assert conn.rolled_back is True
    assert (columns, rows) == (["x"], [(1,)])


def test_refuses_a_connection_that_is_not_in_autocommit_mode():
    with pytest.raises(ValueError):
        db.run_readonly(FakeConnection(autocommit=False), "SELECT 1")


def test_reader_url_never_falls_back_to_the_owner_login(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "ROOT", tmp_path)   # no .env file
    monkeypatch.delenv("DASHBOARD_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://owner@h/db")
    with pytest.raises(RuntimeError):
        db.reader_url()
