"""Database with metadata search (Feature 5).

What it does:
    Filters saved analyses and notes by HS code (any prefix: HS2, HS4 or HS6),
    importer, supplier, tariff event and date range, using the indexed metadata
    columns in RDS. "Last 6 months" is a one-click preset. The page shows how
    long the query took, to evidence the "under 2 seconds" target.

Inputs:
    Query string: hs, importer, supplier, event_id, date_from, date_to, kind, preset.

Outputs:
    The search page.

How to run:
    Registered by app/app.py at /search.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

from flask import Blueprint, render_template, request

from app import db
from config.settings import settings

bp = Blueprint("search", __name__)


@bp.route("/search")
def page():
    """Run a metadata search and render the results."""
    f = {k: request.args.get(k, "").strip() for k in ("hs", "importer", "supplier", "event_id", "date_from", "date_to")}
    if request.args.get("preset") == "6m":
        f["date_from"] = (date.today() - timedelta(days=183)).isoformat()
        f["date_to"] = date.today().isoformat()
    for k in ("importer", "supplier"):
        f[k] = f[k].upper()
    kind = request.args.get("kind", "both")
    kinds = {"both": ["analysis", "note"], "analysis": ["analysis"], "note": ["note"]}.get(kind, ["analysis", "note"])
    searched = any(f.values()) or "go" in request.args
    results, elapsed_ms = [], None
    if searched:
        t0 = time.perf_counter()
        results = db.search_metadata(f, kinds, settings.search_limit)
        elapsed_ms = (time.perf_counter() - t0) * 1000
    return render_template(
        "search.html", f=f, kind=kind, results=results, elapsed_ms=elapsed_ms, searched=searched, events=db.events()
    )
