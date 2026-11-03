"""Open the warehouse and run .sql files with named parameters."""

import re

import duckdb

from pipeline.settings import REPO_ROOT

SQL_DIR = REPO_ROOT / "sql"
PARAMETER = re.compile(r"\$([a-z_]+)")
LINE_COMMENT = re.compile(r"--[^\n]*")


def connect(warehouse_path):
    warehouse_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(warehouse_path))
    # By default DuckDB rewrites its main file every 16 MB of changes ("checkpoint").
    # A backfill makes ~5 MB of changes a day, so that meant a rewrite every few
    # days; one checkpoint when the connection closes is enough.
    con.execute("SET checkpoint_threshold = '4GB'")
    return con


def statements(sql_text):
    """Split a file into statements, after removing -- comments (which may contain ';').
    Our SQL never has ';' or '--' inside a string."""
    without_comments = LINE_COMMENT.sub("", sql_text)
    return [s.strip() for s in without_comments.split(";") if s.strip()]


def execute(con, sql, params=None):
    """Run one statement, passing only the $parameters it actually uses."""
    names = set(PARAMETER.findall(sql))
    if not names:
        return con.execute(sql)
    params = params or {}
    missing = names - params.keys()
    if missing:
        raise KeyError(f"SQL needs parameters that were not given: {sorted(missing)}")
    return con.execute(sql, {name: params[name] for name in names})


def run_sql_file(con, relative_path, params=None):
    """Run every statement in sql/<relative_path>, in order."""
    for statement in statements((SQL_DIR / relative_path).read_text(encoding="utf-8")):
        execute(con, statement, params)


def scalar(con, sql, params=None):
    return execute(con, sql, params).fetchone()[0]
