"""Query checker for "Ask the data" (DL-026, guardrail 2).

Every query a language model writes passes through `check()` before it reaches
the database. It is one of several independent layers: the database role is
read-only with a statement timeout, so this checker is not the only defence,
and it must hold even if the other layers fail.

Rules:
- exactly one statement, and it must be a query (SELECT, possibly with WITH or
  UNION); no SELECT ... INTO, no FOR UPDATE/SHARE, no data-modifying CTEs
- only the allowed marts, written as marts.<table> or bare <table>; bare names
  are qualified here, so the search_path cannot redirect them
- functions: no denied functions (sleep, file and server access, settings);
  any function sqlglot does not recognise must be on a short allowlist
- every JOIN has an ON or USING condition
- at most MAX_ROWS rows: a LIMIT is added, or a larger one lowered

Expensive but valid queries (e.g. JOIN ... ON true) are not all detectable
here; the database's statement timeout is what stops them.

The SQL that runs is sqlglot's rendering of the checked tree, not the original
text, so what was checked is exactly what runs.
"""
from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

SCHEMA = "marts"
ALLOWED_TABLES = frozenset({
    "fct_risk_index_monthly",
    "fct_risk_index_ipc",
    "fct_climate_county_monthly",
    "fct_ipc_county_analysis",
    "fct_maize_price_monthly",
    "fct_price_forecast",
})
MAX_ROWS = 500
MAX_SQL_CHARS = 5000

# Statement types that are never allowed anywhere in the tree (including in a CTE).
FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop,
    exp.Alter, exp.TruncateTable, exp.Copy, exp.Command, exp.Set, exp.Use,
    exp.Grant, exp.Revoke, exp.Transaction, exp.Commit, exp.Rollback,
    exp.Lock, exp.Into, exp.LoadData, exp.Pragma, exp.Describe,
)

# Denied by name prefix or exact name, whatever sqlglot calls them.
DENIED_PREFIXES = ("pg_", "lo_", "dblink", "txid_", "xml", "query_to_", "table_to_",
                   "database_to_", "schema_to_", "cursor_to_")
DENIED_FUNCTIONS = frozenset({
    "current_setting", "set_config", "version", "current_version", "inet_server_addr", "inet_server_port",
    "inet_client_addr", "current_user", "session_user", "user", "current_database",
    "current_schema", "current_schemas", "has_table_privilege", "has_schema_privilege",
    "has_function_privilege", "has_database_privilege", "to_regclass", "to_regproc",
    "to_regnamespace", "obj_description", "col_description", "format_type",
    "nextval", "setval", "currval", "lastval", "gen_random_uuid", "uuid_generate_v4",
})

# Unquoted keywords PostgreSQL treats as server information when used like a column.
SERVER_KEYWORDS = frozenset({"user", "current_user", "session_user", "current_role",
                             "current_catalog", "current_schema"})

# Functions sqlglot does not model (parsed as Anonymous) that are fine for analysis.
ALLOWED_ANONYMOUS = frozenset({
    "num_nonnulls", "num_nulls", "date_part", "to_char", "to_date", "make_date",
    "justify_interval", "width_bucket", "percentile_cont", "percentile_disc",
    "mode", "regr_slope", "regr_intercept", "regr_r2", "initcap", "btrim",
    "split_part", "age", "trunc", "sign", "div", "mod", "scale",
})


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    sql: str | None = None      # the SQL to run (only when ok)
    reason: str | None = None   # why it was rejected (only when not ok)


def _reject(reason: str) -> GuardResult:
    return GuardResult(ok=False, reason=reason)


def _identifier(node: exp.Expression | None) -> str:
    """A name as PostgreSQL resolves it: unquoted names fold to lower case, quoted ones don't."""
    if node is None:
        return ""
    if isinstance(node, exp.Identifier):
        return node.this if node.quoted else node.this.lower()
    return node.name.lower()   # e.g. a function used as a table


def _function_names(f: exp.Func) -> set[str]:
    """The function's names: sqlglot's own, and as rendered for PostgreSQL.

    sqlglot renames some functions internally (version() is CURRENT_VERSION),
    so both are checked against the deny rules.
    """
    if isinstance(f, exp.Anonymous):
        return {str(f.name).lower()}
    rendered = f.sql(dialect="postgres").split("(", 1)[0].strip().lower()
    return {f.sql_name().lower(), rendered}


def check(sql: str) -> GuardResult:
    """Check one model-written query. Returns the SQL to run, or the reason it was rejected."""
    if not sql or not sql.strip():
        return _reject("The query is empty.")
    if len(sql) > MAX_SQL_CHARS:
        return _reject(f"The query is longer than {MAX_SQL_CHARS} characters.")

    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except (ParseError, TokenError) as e:
        return _reject(f"The query could not be parsed: {str(e).splitlines()[0]}")
    if len(statements) != 1:
        return _reject("Exactly one statement is allowed.")
    tree = statements[0]

    if not isinstance(tree, exp.Query) or isinstance(tree, exp.Values):
        return _reject("Only SELECT queries are allowed.")

    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            return _reject(f"{type(node).__name__.upper()} is not allowed; only reading data is.")
        if isinstance(node, exp.Select) and (node.args.get("into") or node.args.get("locks")):
            return _reject("SELECT ... INTO and FOR UPDATE/SHARE are not allowed.")

    # Joins need a condition. This blocks the obvious row explosions (CROSS JOIN,
    # comma joins, NATURAL JOIN); a deliberate one such as JOIN ... ON true still
    # passes, which is what the database's statement timeout is for.
    for join in tree.find_all(exp.Join):
        if not (join.args.get("on") or join.args.get("using")):
            return _reject("Every JOIN needs an ON or USING condition (no CROSS, NATURAL or comma joins).")

    # Tables: CTE names are fine; everything else must be an allowed mart.
    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        name = _identifier(table.args.get("this"))
        schema = _identifier(table.args.get("db"))
        if table.args.get("catalog"):
            return _reject(f"Table {table.sql('postgres')} is not allowed.")
        if not schema and name in cte_names:
            continue
        if not name:   # e.g. a table function such as generate_series(...)
            continue
        if name not in ALLOWED_TABLES or schema not in ("", SCHEMA):
            allowed = ", ".join(f"{SCHEMA}.{t}" for t in sorted(ALLOWED_TABLES))
            return _reject(f"Table {table.sql('postgres')} is not allowed. Allowed tables: {allowed}.")
        if not schema:
            table.set("db", exp.to_identifier(SCHEMA))

    # Functions.
    for f in tree.find_all(exp.Func):
        names = _function_names(f)
        for name in names:
            if name in DENIED_FUNCTIONS or name.startswith(DENIED_PREFIXES):
                return _reject(f"Function {name}() is not allowed.")
        if isinstance(f, exp.Anonymous) and not names <= ALLOWED_ANONYMOUS:
            return _reject(f"Function {min(names)}() is not on the allowed list.")

    # Bare keywords that PostgreSQL reads as server information, not columns.
    for col in tree.find_all(exp.Column):
        if not col.table and _identifier(col.args.get("this")) in SERVER_KEYWORDS:
            return _reject(f"{col.name} is not allowed.")

    # Row limit on the outermost query.
    limit = tree.args.get("limit")
    current = None
    if limit is not None:
        value = limit.args.get("expression")
        if isinstance(value, exp.Literal) and value.is_int:
            current = int(value.this)
        else:
            return _reject("LIMIT must be a whole number.")
    if current is None or current > MAX_ROWS:
        tree = tree.limit(MAX_ROWS, copy=False)

    return GuardResult(ok=True, sql=tree.sql(dialect="postgres"))
