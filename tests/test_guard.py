"""Tests for the query checker (DL-026, guardrail 2). No database or model needed."""
from pathlib import Path

import pytest
import sqlglot
import yaml

from nlq.guard import ALLOWED_TABLES, MAX_ROWS, check

ROOT = Path(__file__).resolve().parents[1]
ACCURACY = yaml.safe_load((ROOT / "nlq/evals/accuracy.yaml").read_text(encoding="utf-8"))["questions"]
ATTACKS = yaml.safe_load((ROOT / "nlq/evals/attacks.yaml").read_text(encoding="utf-8"))["questions"]


# ---------- the pre-registered sets ----------

@pytest.mark.parametrize("q", ACCURACY, ids=[q["id"] for q in ACCURACY])
def test_every_reference_query_is_allowed(q):
    result = check(q["sql"])
    assert result.ok, result.reason


@pytest.mark.parametrize("q", [q for q in ATTACKS if "probe_sql" in q],
                         ids=[q["id"] for q in ATTACKS if "probe_sql" in q])
def test_every_attack_probe_is_rejected_by_the_checker_alone(q):
    result = check(q["probe_sql"])
    assert not result.ok
    assert result.reason


def test_allowlist_matches_the_dbt_marts():
    marts = {p.stem for p in (ROOT / "dbt/models/marts").glob("fct_*.sql")}
    assert ALLOWED_TABLES == marts


# ---------- more ways to write or reach outside marts ----------

REJECTED = {
    "delete in a CTE": "with d as (delete from marts.fct_price_forecast returning *) select * from d",
    "insert in a CTE": "with i as (insert into marts.fct_price_forecast default values returning *) select 1",
    "update in a CTE": "with u as (update marts.fct_price_forecast set horizon = 9 returning *) select * from u",
    "for update": "select * from marts.fct_price_forecast for update",
    "for share": "select * from marts.fct_price_forecast for share",
    "explain analyze": "explain analyze select * from marts.fct_price_forecast",
    "copy to file": "copy marts.fct_price_forecast to '/tmp/x.csv'",
    "copy from program": "copy marts.fct_price_forecast from program 'id'",
    "call": "call do_something()",
    "do block": "do $$ begin perform pg_sleep(10); end $$",
    "vacuum": "vacuum marts.fct_price_forecast",
    "lock": "lock table marts.fct_price_forecast",
    "set role": "set role postgres",
    "reset": "reset all",
    "show": "show data_directory",
    "notify": "notify channel, 'x'",
    "prepare": "prepare p as select 1",
    "begin": "begin",
    "values": "values (1), (2)",
    "create table as": "create table t as select * from marts.fct_price_forecast",
    "two selects": "select 1; select 2",
    "staging schema": "select * from staging.stg_fpma__maize_retail",
    "reference schema": "select * from reference.dim_county",
    "forecasts schema": "select * from forecasts.maize_price_forecast_runs",
    "information_schema": "select * from information_schema.tables",
    "pg_catalog": "select * from pg_catalog.pg_tables",
    "unknown mart": "select * from marts.fct_secret",
    "quoted other schema": 'select * from "Marts".fct_price_forecast',
    "catalog-qualified": "select * from otherdb.marts.fct_price_forecast",
    "pg_sleep in a subquery": "select * from marts.fct_price_forecast where horizon = (select 1 from pg_sleep(5))",
    "pg_sleep in where": "select * from marts.fct_price_forecast where pg_sleep(5) is not null",
    "file as table": "select * from pg_read_file('/etc/passwd') f",
    "dblink": "select * from dblink('host=evil', 'select 1') as t(x int)",
    "large object": "select lo_import('/etc/passwd')",
    "set_config": "select set_config('statement_timeout', '0', false)",
    "version": "select version()",
    "current_user": "select current_user",
    "unknown function": "select made_up_function(1)",
    "cross join": "select count(*) from marts.fct_price_forecast cross join marts.fct_risk_index_monthly",
    "comma join": "select count(*) from marts.fct_price_forecast a, marts.fct_risk_index_monthly b",
    "natural join": "select * from marts.fct_price_forecast natural join marts.fct_maize_price_monthly",
    "bare user keyword": "select user",
    "current_database": "select current_database()",
    "session_user": "select session_user",
    "limit subquery": "select * from marts.fct_price_forecast limit (select 100000)",
    "empty": "   ",
    "comment only": "-- nothing here",
    "not sql": "show me the top counties please",
    "too long": "select 1 " + " " * 6000,
}


@pytest.mark.parametrize("sql", REJECTED.values(), ids=REJECTED.keys())
def test_rejected(sql):
    result = check(sql)
    assert not result.ok, f"allowed: {result.sql}"
    assert result.reason


# ---------- what it allows, and how it rewrites ----------

def test_bare_table_names_are_qualified_with_marts():
    result = check("select county_name from fct_price_forecast")
    assert result.ok
    assert "marts.fct_price_forecast" in result.sql


def test_cte_names_are_not_mistaken_for_tables():
    result = check("with x as (select county_name from marts.fct_price_forecast) select * from x")
    assert result.ok


def test_missing_limit_is_added():
    result = check("select county_name from marts.fct_price_forecast")
    assert sqlglot.parse_one(result.sql, read="postgres").args["limit"].expression.this == str(MAX_ROWS)


def test_large_limit_is_lowered_and_small_one_kept():
    assert f"LIMIT {MAX_ROWS}" in check("select 1 from marts.fct_price_forecast limit 100000").sql
    assert f"LIMIT {MAX_ROWS}" in check("select 1 from marts.fct_price_forecast limit all").sql
    assert "LIMIT 5" in check("select 1 from marts.fct_price_forecast limit 5").sql


def test_union_of_allowed_tables_is_allowed_and_limited():
    result = check("select county_name from marts.fct_price_forecast "
                   "union select county_name from marts.fct_maize_price_monthly")
    assert result.ok and f"LIMIT {MAX_ROWS}" in result.sql


def test_known_gap_join_on_true_passes_the_checker():
    """A deliberate row explosion with a trivial condition passes the checker.
    DL-026: the database's statement timeout is the layer that stops it."""
    assert check("select count(*) from marts.fct_price_forecast a "
                 "join marts.fct_risk_index_monthly b on true").ok
