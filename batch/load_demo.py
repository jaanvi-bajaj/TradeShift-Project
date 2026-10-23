"""Load the demo analyses and notes into a new stack, so the History page is not empty.

What it does:
    If the snapshot contains processed/demo/tradeshift-export.zip (made with the
    History page's Export button) and the analyses table is empty, imports it with
    app/backup.py. A stack that already has saved work is left alone.

Inputs:
    processed/demo/tradeshift-export.zip in storage; RDS.

Outputs:
    Rows in the analyses and notes tables; Markdown files under analyses/.

How to run:
    python -m batch.load_demo
"""

from __future__ import annotations

import logging

from app.backup import import_bundle
from batch.storage_io import store
from config.database import apply_schema, connect
from config.logging_config import setup_logging
from config.settings import settings

log = logging.getLogger("load_demo")

DEMO_KEY = f"{settings.processed_prefix}demo/tradeshift-export.zip"


def run() -> dict[str, int] | None:
    """Import the demo bundle once into an empty stack.

    Returns:
        Import counts, or None if there was nothing to do.
    """
    if not store.exists(DEMO_KEY):
        log.info("No demo bundle in the snapshot; skipping")
        return None
    apply_schema()
    with connect() as conn:
        if conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0] > 0:
            log.info("Saved analyses already exist; demo bundle not loaded")
            return None
        result = import_bundle(conn, store, store.read_bytes(DEMO_KEY))
    log.info("Demo content loaded: %s", result)
    return result


if __name__ == "__main__":
    setup_logging()
    run()
