"""Run dbt with connection details taken from DATABASE_URL.

DATABASE_URL (in .env locally, or a GitHub secret in CI) is the only place
the connection string lives. This script splits it into the DBT_PG_* values
that dbt/profiles.yml reads, then runs dbt against the project in dbt/.

Usage (from the repo root), with any normal dbt arguments:
    python scripts/run_dbt.py debug
    python scripts/run_dbt.py seed
    python scripts/run_dbt.py build
"""
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DBT_DIR = ROOT / "dbt"


def export_connection(url: str) -> None:
    u = urlparse(url)
    query = parse_qs(u.query)
    os.environ["DBT_PG_HOST"] = u.hostname or ""
    os.environ["DBT_PG_PORT"] = str(u.port or 5432)
    os.environ["DBT_PG_USER"] = unquote(u.username or "")
    os.environ["DBT_PG_PASSWORD"] = unquote(u.password or "")
    os.environ["DBT_PG_DBNAME"] = u.path.lstrip("/") or "postgres"
    os.environ["DBT_PG_SSLMODE"] = query.get("sslmode", ["require"])[0]


def main() -> int:
    load_dotenv(ROOT / ".env")
    if "DATABASE_URL" not in os.environ:
        print("DATABASE_URL is not set (add it to .env)", file=sys.stderr)
        return 2
    export_connection(os.environ["DATABASE_URL"])

    from dbt.cli.main import dbtRunner   # imported after the environment is set

    args = sys.argv[1:] or ["debug"]
    if args[0] not in ("--version", "-v"):
        if "--project-dir" not in args:
            args += ["--project-dir", str(DBT_DIR)]
        if "--profiles-dir" not in args:
            args += ["--profiles-dir", str(DBT_DIR)]
    result = dbtRunner().invoke(args)
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
