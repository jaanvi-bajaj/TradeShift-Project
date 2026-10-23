"""Download monthly US imports by country and HS6 product from the US Census API.

What it does:
    For every month from START_MONTH to the latest published month, requests all
    HS6 products by country of origin and saves the raw JSON response, gzipped,
    to raw/census/YYYY-MM.json.gz. A month already in storage is skipped, so raw
    data is downloaded once and never again (Data rules).

Inputs:
    CENSUS_API_KEY (free), settings.start_month, settings.last_month.

Outputs:
    raw/census/YYYY-MM.json.gz in S3 (or LOCAL_DATA_DIR), one per month.

How to run:
    python -m batch.download_census            # all missing months
    python -m batch.download_census --month 2018-07
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from batch.storage_io import store
from config.logging_config import setup_logging
from config.settings import settings

log = logging.getLogger("download_census")

# GEN_VAL_MO is general imports, the Census headline import measure; quantities
# (GEN_QY1_MO with its unit) feed the "higher confidence" check in the detector.
CENSUS_WORKERS = int(os.environ.get("CENSUS_WORKERS", "4"))

FIELDS = "CTY_CODE,CTY_NAME,I_COMMODITY,I_COMMODITY_SDESC,GEN_VAL_MO,GEN_QY1_MO,UNIT_QY1"


def month_range(start: str, end: str) -> list[str]:
    """Return every month from start to end inclusive, as YYYY-MM strings.

    Args:
        start: First month, "YYYY-MM".
        end: Last month, "YYYY-MM".

    Returns:
        Ordered list of months.
    """
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def raw_key(month: str) -> str:
    """Return the storage key for one month's raw Census response."""
    return f"{settings.raw_prefix}census/{month}.json.gz"


def fetch_month(month: str, session: requests.Session) -> list[list[str]] | None:
    """Request one month of HS6-by-country imports.

    Args:
        month: "YYYY-MM".
        session: Reused HTTP session.

    Returns:
        The API's table (first row is the header), or None if the month is not
        published yet (the API answers 204 No Content).
    """
    params = {"get": FIELDS, "COMM_LVL": "HS6", "time": month, "key": settings.census_api_key}
    for attempt in range(1, 5):
        try:
            # A full month takes the API about 4 minutes to build, longer when busy.
            resp = session.get(settings.census_url, params=params, timeout=900)
        except requests.RequestException as exc:
            log.warning("Census %s: connection error (attempt %d): %s", month, attempt, exc)
            time.sleep(30 * attempt)
            continue
        if resp.status_code == 204:
            return None
        if resp.status_code == 200:
            return resp.json()
        # Retry server errors with a growing wait; anything else is a real problem.
        log.warning("Census %s: HTTP %s (attempt %d)", month, resp.status_code, attempt)
        if resp.status_code < 500:
            resp.raise_for_status()
        time.sleep(10 * attempt)
    raise RuntimeError(f"Census API failed for {month}")


def run(months: list[str] | None = None) -> int:
    """Download every month that is not in storage yet.

    Args:
        months: Months to fetch; defaults to START_MONTH..latest.

    Returns:
        Number of months downloaded in this run.
    """
    if not settings.census_api_key:
        raise SystemExit("CENSUS_API_KEY is not set (see .env.example)")
    months = [
        m for m in (months or month_range(settings.start_month, settings.last_month)) if not store.exists(raw_key(m))
    ]
    downloaded = 0

    def fetch_and_save(month: str) -> bool:
        """Fetch one month and store it; False if the month is not published yet."""
        table = fetch_month(month, requests.Session())
        if table is None:
            log.info("Census %s not published yet", month)
            return False
        store.write_json_gz(raw_key(month), table)
        log.info("Census %s: saved %d rows", month, len(table) - 1)
        return True

    # A full month takes about four minutes for the API to build, so a few months are
    # requested at once. CENSUS_WORKERS keeps this polite (default 4).
    with ThreadPoolExecutor(max_workers=CENSUS_WORKERS) as pool:
        downloaded = sum(pool.map(fetch_and_save, months))
    log.info("Census download finished: %d new months", downloaded)
    return downloaded


if __name__ == "__main__":
    setup_logging()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--month", help="download a single month, YYYY-MM")
    args = parser.parse_args()
    run([args.month] if args.month else None)
