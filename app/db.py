"""Every database query the web app runs.

What it does:
    Keeps SQL out of the views: each page calls a named function here. One
    connection per request (opened lazily, closed when the request ends), so web
    servers hold no state between requests and can be added or removed by the
    Auto Scaling Group at any time.

Inputs:
    RDS connection settings (config/settings.py).

Outputs:
    pandas DataFrames or lists of dicts for the views.

How to run:
    Not run directly; imported by app/views/*.py.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pandas as pd
from flask import g
from psycopg.rows import dict_row

from config.database import connect
from config.settings import settings


def conn():
    """Return this request's database connection, opening it on first use."""
    if "db" not in g:
        g.db = connect(autocommit=True)
    return g.db


def close(_exc: BaseException | None = None) -> None:
    """Close this request's connection (registered as a Flask teardown)."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def rows(sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
    """Run a query and return rows as dicts."""
    with conn().cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def frame(sql: str, params: tuple | dict = ()) -> pd.DataFrame:
    """Run a query and return a DataFrame."""
    return pd.DataFrame(rows(sql, params))


def one(sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
    """Run a query and return the first row, or None."""
    result = rows(sql, params)
    return result[0] if result else None


# ------------------------------------------------------------------ reference data


def countries() -> dict[str, str]:
    """Return {iso2: short name} for every country, e.g. {"CN": "China"}."""
    return {r["iso2"]: r["name"].split(" (")[0] for r in rows("SELECT iso2, name FROM countries")}


def events() -> list[dict[str, Any]]:
    """Return every tariff event, oldest first."""
    return rows("SELECT * FROM tariff_events ORDER BY effective_date, event_id")


def product(hs6: str) -> dict[str, Any] | None:
    """Return one product's code, heading and description."""
    return one("SELECT * FROM products WHERE hs6 = %s", (hs6,))


def search_products(q: str, limit: int = 20) -> list[dict[str, Any]]:
    """Find products by HS code prefix or a word in the description."""
    q = q.strip().replace(".", "")
    if q.isdigit():
        return rows("SELECT hs6, description FROM products WHERE hs6 LIKE %s ORDER BY hs6 LIMIT %s", (q + "%", limit))
    return rows(
        "SELECT hs6, description FROM products WHERE lower(description) LIKE %s ORDER BY hs6 LIMIT %s",
        ("%" + q.lower() + "%", limit),
    )


def product_events(hs6: str) -> list[dict[str, Any]]:
    """Return the tariff events that cover a product."""
    return rows(
        """SELECT DISTINCT e.event_id, e.name, e.effective_date, e.source_url
           FROM tariff_event_products p JOIN tariff_events e USING (event_id)
           WHERE p.hs6 = %s ORDER BY e.effective_date""",
        (hs6,),
    )


def importers() -> list[str]:
    """Return the importers that have data, US first."""
    found = [r["importer"] for r in rows("SELECT DISTINCT importer FROM hhi_monthly")]
    return sorted(found, key=lambda i: (i != "US", i))


# ------------------------------------------------------------------ trade series


def trade_series(importer: str, hs6: str) -> pd.DataFrame:
    """Monthly value and quantity by supplier for one importer and product."""
    return frame(
        "SELECT supplier, month, value_usd, qty, qty_unit FROM trade_monthly WHERE importer=%s AND hs6=%s ORDER BY month",
        (importer, hs6),
    )


def supplier_series(importer: str, supplier: str, hs6: str) -> pd.DataFrame:
    """Monthly value of one supplier and of the whole market, for one importer and product."""
    return frame(
        """SELECT month, SUM(value_usd) AS total,
                  SUM(value_usd) FILTER (WHERE supplier = %s) AS supplier_value
           FROM trade_monthly WHERE importer=%s AND hs6=%s GROUP BY month ORDER BY month""",
        (supplier, importer, hs6),
    )


def hhi_series(importer: str, hs6: str) -> pd.DataFrame:
    """Monthly HHI (and 12-month rolling HHI) for one importer and product."""
    return frame(
        "SELECT month, total_value, n_suppliers, hhi, hhi_12m FROM hhi_monthly WHERE importer=%s AND hs6=%s ORDER BY month",
        (importer, hs6),
    )


def data_status() -> dict[str, Any]:
    """Row counts and month coverage, shown on the home page and /health."""
    status = one(
        """SELECT (SELECT COUNT(*) FROM signals) AS signals,
                  (SELECT COUNT(*) FROM products) AS products,
                  (SELECT MIN(month) FROM hhi_monthly WHERE importer='US') AS first_month,
                  (SELECT MAX(month) FROM hhi_monthly WHERE importer='US') AS last_month"""
    )
    return status or {}


def totals_check() -> pd.DataFrame:
    """Our country sum against the Census all-countries total, by month."""
    return frame("SELECT * FROM totals_check ORDER BY month")


# ------------------------------------------------------------------ signals


def event_shares(event_id: str | None) -> pd.DataFrame:
    """Before/after supplier shares for one event (or all events if None)."""
    if event_id:
        return frame("SELECT * FROM event_shares WHERE event_id=%s", (event_id,))
    return frame("SELECT * FROM event_shares")


def event_products(event_id: str | None) -> pd.DataFrame:
    """Before/after totals and HHI per product for one event (or all)."""
    if event_id:
        return frame("SELECT * FROM event_products WHERE event_id=%s", (event_id,))
    return frame("SELECT * FROM event_products")


def event_product(event_id: str, hs6: str) -> dict[str, Any] | None:
    """Totals and HHI for one event and product."""
    return one("SELECT * FROM event_products WHERE event_id=%s AND hs6=%s", (event_id, hs6))


def signals(event_id: str | None = None, hs6: str | None = None, limit: int = 200) -> pd.DataFrame:
    """Stored detector flags (default thresholds), largest value redirected first."""
    where, params = [], []
    if event_id:
        where.append("s.event_id = %s")
        params.append(event_id)
    if hs6:
        where.append("s.hs6 = %s")
        params.append(hs6)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    # A product can sit on two overlapping lists (part of an HS6 on List 1, part on
    # List 3). Across all events, keep only its largest shift for each losing supplier.
    return frame(
        f"""SELECT * FROM (
                SELECT DISTINCT ON (s.hs6, s.loser) s.*, p.description
                FROM signals s LEFT JOIN products p USING (hs6) {clause}
                ORDER BY s.hs6, s.loser, s.value_redirected_usd DESC
            ) best ORDER BY value_redirected_usd DESC LIMIT %s""",
        (*params, limit),
    )


def did_results() -> dict[str, dict[str, Any]]:
    """DiD validation results keyed by event_id."""
    return {r["event_id"]: r for r in rows("SELECT * FROM did_results")}


def hhi_changes(event_id: str, limit: int = 20) -> pd.DataFrame:
    """Products with the largest HHI change for one event (above the value floor)."""
    return frame(
        """SELECT e.*, p.description, e.hhi_after - e.hhi_before AS hhi_change
           FROM event_products e LEFT JOIN products p USING (hs6)
           WHERE e.event_id=%s AND e.total_before >= %s
           ORDER BY ABS(e.hhi_after - e.hhi_before) DESC LIMIT %s""",
        (event_id, settings.min_annual_value_usd, limit),
    )


# ------------------------------------------------------------------ Singapore lens


def singapore_lens(flagged_only: bool = True, limit: int = 50) -> pd.DataFrame:
    """Products ranked by estimated Singapore re-exports to the US after the tariffs."""
    clause = "WHERE flagged" if flagged_only else ""
    return frame(
        f"""SELECT l.*, p.description FROM singapore_lens l LEFT JOIN products p USING (hs6)
            {clause} ORDER BY est_rx_after DESC LIMIT %s""",
        (limit,),
    )


def singapore_totals() -> pd.DataFrame:
    """Monthly official re-exports and domestic exports to the US (SingStat), plus the sum of our HS6 estimates."""
    return frame(
        """SELECT o.month, o.rx_usd, o.dx_usd, e.est_rx_usd
           FROM singapore_official o
           LEFT JOIN (SELECT month, SUM(est_reexports_usd) AS est_rx_usd FROM singapore_monthly GROUP BY month) e
           USING (month) ORDER BY o.month"""
    )


def singapore_product(hs6: str) -> pd.DataFrame:
    """Monthly exports, Singapore-origin imports and estimated re-exports for one product."""
    return frame("SELECT * FROM singapore_monthly WHERE hs6=%s ORDER BY month", (hs6,))


# ------------------------------------------------------------------ saved analyses (Feature 3, 5)


def insert_analysis(
    title: str,
    view: str,
    s3_key: str,
    meta: dict[str, Any],
    params: dict[str, Any],
    instance_id: str,
    analysis_id: str | None = None,
) -> str:
    """Record a saved analysis's metadata; the analysis itself is already in S3.

    Returns:
        The analysis ID (a UUID string).
    """
    analysis_id = analysis_id or str(uuid.uuid4())
    conn().execute(
        """INSERT INTO analyses (id, title, view, s3_key, hs6, importer, supplier, event_id, params, instance_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            analysis_id,
            title,
            view,
            s3_key,
            meta.get("hs6") or None,
            meta.get("importer") or None,
            meta.get("supplier") or None,
            meta.get("event_id") or None,
            json.dumps(params),
            instance_id,
        ),
    )
    return analysis_id


def list_analyses(limit: int = 100) -> list[dict[str, Any]]:
    """Saved analyses, newest first."""
    return rows("SELECT * FROM analyses ORDER BY created_at DESC LIMIT %s", (limit,))


def get_analysis(analysis_id: str) -> dict[str, Any] | None:
    """One saved analysis's metadata row."""
    try:
        uuid.UUID(analysis_id)
    except ValueError:
        return None
    return one("SELECT * FROM analyses WHERE id=%s", (analysis_id,))


# ------------------------------------------------------------------ notes (Feature 4, 5)


def add_note(target_type: str, target_id: str, body: str, meta: dict[str, Any], instance_id: str) -> None:
    """Save a note on a product or a saved analysis, with its search metadata."""
    conn().execute(
        """INSERT INTO notes (target_type, target_id, hs6, importer, supplier, event_id, body, instance_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            target_type,
            target_id,
            meta.get("hs6") or None,
            meta.get("importer") or None,
            meta.get("supplier") or None,
            meta.get("event_id") or None,
            body,
            instance_id,
        ),
    )


def notes_for(target_type: str, target_id: str) -> list[dict[str, Any]]:
    """Notes on one product or analysis, newest first."""
    return rows(
        "SELECT * FROM notes WHERE target_type=%s AND target_id=%s ORDER BY created_at DESC", (target_type, target_id)
    )


def recent_notes(limit: int = 100) -> list[dict[str, Any]]:
    """The newest notes across the app."""
    return rows("SELECT * FROM notes ORDER BY created_at DESC LIMIT %s", (limit,))


# ------------------------------------------------------------------ metadata search (Feature 5)


def search_metadata(filters: dict[str, str], kinds: list[str], limit: int) -> list[dict[str, Any]]:
    """Search saved analyses and notes by HS code, importer, supplier, event and date.

    Args:
        filters: Any of hs (code prefix, e.g. "8450"), importer, supplier, event_id,
            date_from, date_to (YYYY-MM-DD).
        kinds: "analysis" and/or "note".
        limit: Maximum rows.

    Returns:
        Matching rows from both tables in one list, newest first.
    """
    where, params = [], []
    if filters.get("hs"):
        where.append("hs6 LIKE %s")
        params.append(filters["hs"].replace(".", "") + "%")
    for field in ("importer", "supplier", "event_id"):
        if filters.get(field):
            where.append(f"{field} = %s")
            params.append(filters[field])
    if filters.get("date_from"):
        where.append("created_at >= %s::date")
        params.append(filters["date_from"])
    if filters.get("date_to"):
        where.append("created_at < %s::date + 1")
        params.append(filters["date_to"])
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    parts = []
    if "analysis" in kinds:
        parts.append(
            f"""SELECT 'analysis' AS kind, id::text AS id, title AS text, view, hs6, importer, supplier,
                                event_id, created_at FROM analyses {clause}"""
        )
    if "note" in kinds:
        parts.append(
            f"""SELECT 'note' AS kind, target_id AS id, body AS text, target_type AS view, hs6, importer,
                                supplier, event_id, created_at FROM notes {clause}"""
        )
    if not parts:
        return []
    sql = " UNION ALL ".join(f"({p})" for p in parts) + " ORDER BY created_at DESC LIMIT %s"
    return rows(sql, tuple(params * len(parts)) + (limit,))
