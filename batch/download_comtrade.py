"""Download UN Comtrade data: Singapore's exports to the US, US quantities, the second importer.

What it does:
    Three jobs, all monthly HS6, in this order (most important first, because the
    free key allows 500 calls a day):
      1. Singapore's total exports to the US, for the Singapore lens. (Comtrade has
         no re-export/domestic split for Singapore; batch/download_singstat.py adds
         the official totals.)
      2. US imports reported to Comtrade, for the 2017-2020 event windows only. Census
         has no quantities at HS6, and the detector's "higher confidence" check needs
         them, so net weight (kg) comes from here.
      3. Imports of the second importer (Japan by default) from every partner, so the
         explorer and comparison work "by importer".
    Every API call is logged to raw/comtrade/_calls/YYYY-MM-DD.json. The job stops
    before the free key's 500-calls-a-day limit and resumes on the next run,
    because each finished request is saved and skipped later (Data rules).

Inputs:
    COMTRADE_API_KEY (free), settings.start_month, settings.last_month,
    data/countries.csv for partner codes.

Outputs:
    raw/comtrade/sg_X/YYYY.json.gz
    raw/comtrade/imports_842/YYYY-MM[_pN].json.gz   (US, quantity window)
    raw/comtrade/imports_<reporter>/YYYY-MM[_pN].json.gz

How to run:
    python -m batch.download_comtrade
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime

import pandas as pd
import requests

from batch.download_census import month_range
from batch.storage_io import store
from config.logging_config import setup_logging
from config.settings import settings

log = logging.getLogger("download_comtrade")

# The free tier returns at most 100,000 records per call. A response that size is
# probably truncated, so the request is split by partner and tried again.
RECORD_CAP = 100_000
PARTNER_CHUNKS = 4


class QuotaReached(Exception):
    """Raised when today's call budget is used up; the next run resumes."""


class CallLog:
    """Counts and records today's Comtrade calls in storage, so separate runs share one budget."""

    def __init__(self) -> None:
        """Load today's log from storage, or start an empty one."""
        self.key = f"{settings.raw_prefix}comtrade/_calls/{date.today().isoformat()}.json.gz"
        self.calls: list[dict] = store.read_json_gz(self.key) if store.exists(self.key) else []

    def check(self) -> None:
        """Raise QuotaReached if one more call would exceed the daily limit."""
        if len(self.calls) >= settings.comtrade_daily_limit:
            raise QuotaReached(f"{len(self.calls)} Comtrade calls today; limit {settings.comtrade_daily_limit}")

    def record(self, params: dict, status: int, count: int) -> None:
        """Append one call to the log and save it straight away."""
        self.calls.append(
            {
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
                "status": status,
                "count": count,
                **{k: v for k, v in params.items() if k != "subscription-key"},
            }
        )
        store.write_json_gz(self.key, self.calls)


def call_api(params: dict, calls: CallLog, session: requests.Session) -> dict:
    """Make one logged Comtrade request, retrying rate-limit and server errors.

    Args:
        params: Query parameters for /data/v1/get/C/M/HS.
        calls: Today's call log; checked before and updated after the call.
        session: Reused HTTP session.

    Returns:
        The decoded JSON body ({"count": n, "data": [...]}).
    """
    headers = {"Ocp-Apim-Subscription-Key": settings.comtrade_api_key}
    for attempt in range(1, 5):
        calls.check()
        try:
            resp = session.get(settings.comtrade_url, params=params, headers=headers, timeout=300)
        except requests.RequestException as exc:
            # A dropped or timed-out connection still counts against the daily quota.
            calls.record(params, 0, 0)
            log.warning("Comtrade connection error (attempt %d): %s", attempt, exc)
            time.sleep(15 * attempt)
            continue
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        calls.record(params, resp.status_code, int(body.get("count") or 0))
        if resp.status_code == 200:
            return body
        log.warning("Comtrade HTTP %s (attempt %d): %s", resp.status_code, attempt, resp.text[:200])
        if resp.status_code not in (429, 500, 502, 503, 504):
            resp.raise_for_status()
        time.sleep(15 * attempt)
    raise RuntimeError(f"Comtrade failed for {params}")


def partner_chunks() -> list[str]:
    """Split every Comtrade partner code into PARTNER_CHUNKS comma-separated lists."""
    codes = pd.read_csv(settings.country_file, dtype=str)["comtrade_code"].dropna().tolist()
    size = -(-len(codes) // PARTNER_CHUNKS)
    return [",".join(codes[i : i + size]) for i in range(0, len(codes), size)]


def importer_months(reporter: str, months: list[str], calls: CallLog, session: requests.Session) -> None:
    """Download one reporter's monthly HS6 imports from all partners.

    Args:
        reporter: Comtrade reporter code (392 = Japan, 842 = USA).
        months: Months to fetch, YYYY-MM.
        calls: Shared call log.
        session: Reused HTTP session.
    """
    base = {
        "reporterCode": reporter,
        "flowCode": "M",
        "cmdCode": "AG6",
        "partner2Code": "0",
        "customsCode": "C00",
        "motCode": "0",
        "includeDesc": "false",
    }
    for month in months:
        key = f"{settings.raw_prefix}comtrade/imports_{reporter}/{month}.json.gz"
        part_keys = [key.replace(".json.gz", f"_p{i}.json.gz") for i in range(PARTNER_CHUNKS)]
        if store.exists(key) or all(store.exists(k) for k in part_keys):
            continue
        body = call_api({**base, "period": month.replace("-", "")}, calls, session)
        if body.get("count", 0) == 0:
            log.info("Comtrade %s %s: no data yet; stopping", reporter, month)
            return
        if body["count"] < RECORD_CAP:
            store.write_json_gz(key, body["data"])
            log.info("Comtrade %s %s: %d rows", reporter, month, body["count"])
            continue
        # Hit the cap: fetch the same month in partner chunks instead.
        for part_key, partners in zip(part_keys, partner_chunks()):
            if not store.exists(part_key):
                part = call_api({**base, "period": month.replace("-", ""), "partnerCode": partners}, calls, session)
                store.write_json_gz(part_key, part.get("data", []))
                log.info("Comtrade %s %s %s: %d rows", reporter, month, part_key[-10:], part.get("count", 0))


def singapore_exports(calls: CallLog, session: requests.Session) -> None:
    """Download Singapore's total exports to the US by HS6, one call per year (12 months).

    Args:
        calls: Shared call log.
        session: Reused HTTP session.
    """
    months = month_range(settings.start_month, settings.last_month)
    years = sorted({m[:4] for m in months})
    for year in years:
        key = f"{settings.raw_prefix}comtrade/sg_X/{year}.json.gz"
        # The current year is re-fetched until December is published.
        if store.exists(key) and year != years[-1]:
            continue
        periods = ",".join(m.replace("-", "") for m in months if m.startswith(year))
        body = call_api(
            {
                "reporterCode": settings.singapore_code,
                "partnerCode": settings.usa_comtrade_code,
                "flowCode": "X",
                "cmdCode": "AG6",
                "period": periods,
                "partner2Code": "0",
                "customsCode": "C00",
                "motCode": "0",
                "includeDesc": "false",
            },
            calls,
            session,
        )
        if body.get("count", 0) >= RECORD_CAP:
            log.warning("Singapore %s hit the record cap; some rows may be missing", year)
        store.write_json_gz(key, body.get("data", []))
        log.info("Comtrade Singapore exports to US %s: %d rows", year, body.get("count", 0))


def run() -> bool:
    """Run both Comtrade jobs until done or until today's quota is reached.

    Returns:
        True if everything is downloaded, False if the quota stopped the run.
    """
    if not settings.comtrade_api_key:
        raise SystemExit("COMTRADE_API_KEY is not set (see .env.example)")
    calls = CallLog()
    session = requests.Session()
    reporter = (
        pd.read_csv(settings.country_file, dtype=str)
        .set_index("iso2")
        .loc[settings.second_importer_iso2, "comtrade_code"]
    )
    try:
        singapore_exports(calls, session)
        importer_months(
            settings.usa_comtrade_code, month_range(settings.qty_start_month, settings.qty_end_month), calls, session
        )
        importer_months(reporter, month_range(settings.start_month, settings.last_month), calls, session)
    except QuotaReached as exc:
        log.warning("Stopping for today: %s. Run again tomorrow to resume.", exc)
        return False
    log.info("Comtrade download complete (%d calls today)", len(calls.calls))
    return True


if __name__ == "__main__":
    setup_logging()
    run()
