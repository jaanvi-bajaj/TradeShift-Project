"""Open PostgreSQL connections with the settings in config/settings.py.

What it does:
    One function that both the batch job and the web app use to connect to RDS,
    so connection details live in one place.

Inputs:
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD (environment).

Outputs:
    psycopg connections.

How to run:
    Not run directly. `from config.database import connect`.
"""

from __future__ import annotations

from pathlib import Path

import psycopg

from config.settings import REPO_ROOT, settings

SCHEMA_FILES = [REPO_ROOT / "db" / "schema.sql", REPO_ROOT / "db" / "indexes.sql"]


def connect(autocommit: bool = False) -> psycopg.Connection:
    """Open a new connection to the TradeShift database.

    Args:
        autocommit: Commit every statement immediately (used for schema setup).

    Returns:
        An open psycopg connection. Close it, or use it in a `with` block.
    """
    return psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
        connect_timeout=10,
        autocommit=autocommit,
        # RDS encrypts connections; "prefer" also works with a local Postgres without TLS.
        sslmode="prefer",
    )


def apply_schema(files: list[Path] = SCHEMA_FILES) -> None:
    """Create any missing tables and indexes. Safe to run at every start."""
    with connect(autocommit=True) as conn:
        for path in files:
            conn.execute(path.read_text())
