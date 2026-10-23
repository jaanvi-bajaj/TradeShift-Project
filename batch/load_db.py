"""Load the processed tables into RDS PostgreSQL.

What it does:
    Creates the schema if needed, then for each pipeline table runs TRUNCATE and a
    bulk COPY from the processed CSV files, inside one transaction per table. So a
    second run replaces data instead of duplicating it, and a failed load leaves
    the previous data in place (Code standards, "Re-runnable pipeline").
    The app's own tables (analyses, notes) are never touched.

Inputs:
    processed/*.csv.gz in storage, data/*.csv in the repo.

Outputs:
    Rows in RDS (see db/schema.sql).

How to run:
    python -m batch.load_db
"""

from __future__ import annotations

import gzip
import logging
from collections.abc import Iterator

import psycopg

from batch.storage_io import store
from config.database import apply_schema, connect
from config.logging_config import setup_logging
from config.settings import settings

log = logging.getLogger("load_db")

P = settings.processed_prefix
# table -> list of sources. A source is a storage key, a storage prefix ending in "/",
# or a repo file path. Order matters only for readability.
TABLES: dict[str, list[str]] = {
    "countries": [str(settings.country_file)],
    "tariff_events": [str(settings.events_file)],
    "tariff_event_products": [str(settings.event_products_file)],
    "products": [f"{P}products.csv.gz"],
    "trade_monthly": [f"{P}trade/"],
    "hhi_monthly": [f"{P}hhi/"],
    "totals_check": [f"{P}totals_check.csv.gz"],
    "event_shares": [f"{P}event_shares.csv.gz"],
    "event_products": [f"{P}event_products.csv.gz"],
    "signals": [f"{P}signals_explained.csv.gz"],
    "did_results": [f"{P}did_results.csv.gz"],
    "singapore_monthly": [f"{P}singapore.csv.gz"],
    "singapore_official": [f"{P}singapore_official.csv.gz"],
    "singapore_lens": [f"{P}singapore_lens.csv.gz"],
}


def csv_files(source: str) -> Iterator[bytes]:
    """Yield the uncompressed CSV contents of one source, one file at a time.

    Why a generator: the trade table is millions of rows, so files are streamed
    into COPY one by one instead of all being held in memory.
    """
    if source.endswith("/"):
        for key in store.list(source):
            if key.endswith(".csv.gz"):
                yield gzip.decompress(store.read_bytes(key))
    elif source.startswith(P):
        if store.exists(source):
            yield gzip.decompress(store.read_bytes(source))
    else:
        with open(source, "rb") as fh:
            yield fh.read()


def load_table(conn: psycopg.Connection, table: str, sources: list[str]) -> int:
    """Replace one table's rows with the CSV sources.

    Args:
        conn: Open connection (not autocommit); the caller commits.
        table: Table name.
        sources: Where the rows come from (see TABLES).

    Returns:
        Number of rows loaded.
    """
    total = 0
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE {table}")
        if table == "countries":
            # "ROW" bundles small suppliers (batch/clean.py), so it needs a name too.
            cur.execute("INSERT INTO countries (iso2, name, is_eu) VALUES ('ROW', 'Rest of world', false)")
        for source in sources:
            for data in csv_files(source):
                header = data.split(b"\n", 1)[0].decode().strip()
                if not header:
                    continue
                # The CSV header names the columns, so file and table column order can differ.
                with cur.copy(f"COPY {table} ({header}) FROM STDIN WITH (FORMAT csv, HEADER true)") as copy:
                    copy.write(data)
                total += max(cur.rowcount, 0)
    return total


def run() -> None:
    """Create the schema and load every pipeline table."""
    apply_schema()
    with connect() as conn:
        for table, sources in TABLES.items():
            rows = load_table(conn, table, sources)
            conn.commit()
            log.info("Loaded %s: %d rows", table, rows)
        conn.execute("ANALYZE")  # fresh statistics so the planner uses the indexes
        conn.commit()


if __name__ == "__main__":
    setup_logging()
    run()
