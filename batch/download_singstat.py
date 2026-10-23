"""Download Singapore's official re-exports and domestic exports to the US from SingStat.

What it does:
    SingStat (Enterprise Singapore data) splits Singapore's exports into re-exports
    and domestic exports, but by market only at a total level, not by HS6 product.
    This job downloads, for the United States:
      * M451511 Re-Exports By Region And Market, Monthly (S$ million)
      * M451501 Domestic Exports By Region And Market, Monthly (S$ million)
      * M700051 Exchange Rates (Average For Period), Monthly: S$ per US$
    so the Singapore lens can show the official split in US dollars, and check our
    HS6 re-export estimate against it (Data rules: "use SingStat if HS6-by-partner
    detail is available; otherwise Comtrade").

Inputs:
    Internet access to tablebuilder.singstat.gov.sg (no key needed).

Outputs:
    raw/singstat/<table>.json.gz, one per table (the API's JSON, unchanged).

How to run:
    python -m batch.download_singstat
"""

from __future__ import annotations

import logging
import time

import requests

from batch.storage_io import store
from config.logging_config import setup_logging
from config.settings import settings

log = logging.getLogger("download_singstat")

API = "https://tablebuilder.singstat.gov.sg/api/table/tabledata/{table}"
# The API answers browser-like clients more reliably; say who we are, too.
HEADERS = {"User-Agent": "Mozilla/5.0 (TradeShift student project)", "Accept": "application/json"}
TABLES = {
    "M451511": "United States Of America",  # re-exports by market
    "M451501": "United States Of America",  # domestic exports by market
    "M700051": "US Dollar",  # S$ per US$, monthly average
}


def fetch(table: str, row_search: str) -> dict:
    """Fetch the rows of one SingStat table that match `row_search`.

    Args:
        table: SingStat table ID.
        row_search: Text of the row wanted (the API's search filter).

    Returns:
        The API's JSON body.
    """
    for attempt in range(1, 6):
        resp = requests.get(API.format(table=table), params={"search": row_search}, headers=HEADERS, timeout=120)
        if resp.status_code == 200 and resp.json().get("Data", {}).get("row"):
            return resp.json()
        log.warning("SingStat %s: HTTP %s, attempt %d", table, resp.status_code, attempt)
        time.sleep(10 * attempt)  # the API rate-limits bursts with HTTP 403
    raise RuntimeError(f"SingStat {table} failed")


def run() -> int:
    """Download every table that is not stored yet.

    Returns:
        Number of tables downloaded.
    """
    done = 0
    for table, row in TABLES.items():
        key = f"{settings.raw_prefix}singstat/{table}.json.gz"
        if store.exists(key):
            continue
        store.write_json_gz(key, fetch(table, row))
        log.info("SingStat %s saved", table)
        done += 1
        time.sleep(3)
    return done


if __name__ == "__main__":
    setup_logging()
    run()
