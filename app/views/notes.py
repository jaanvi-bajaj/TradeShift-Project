"""Save user notes (Feature 4) on any product or saved analysis.

What it does:
    POST /notes adds a note to a product (target_type "product", target_id = HS6)
    or a saved analysis (target_type "analysis", target_id = its UUID), with the
    same metadata the Search page filters on. Notes live in RDS, not on the web
    server, so they survive a restart and are visible from every instance the
    Auto Scaling Group runs. /notes lists the newest notes.

Inputs:
    Form fields: target_type, target_id, body, hs6, importer, supplier, event_id, next.

Outputs:
    A row in the notes table; the notes page.

How to run:
    Registered by app/app.py.
"""

from __future__ import annotations

from urllib.parse import urlparse

from flask import Blueprint, abort, redirect, render_template, request

from app import db
from app.views.common import instance_identity

bp = Blueprint("notes", __name__)

MAX_NOTE = 5000  # characters


@bp.route("/notes", methods=["POST"])
def add():
    """Save one note and return to the page it was written on."""
    target_type = request.form.get("target_type", "")
    target_id = request.form.get("target_id", "").strip()
    body = request.form.get("body", "").strip()
    if target_type not in ("product", "analysis") or not target_id or not body:
        abort(400, "A note needs a target and some text")
    meta = {k: request.form.get(k, "").strip() for k in ("hs6", "importer", "supplier", "event_id")}
    db.add_note(target_type, target_id, body[:MAX_NOTE], meta, instance_identity()["instance_id"])
    # Only redirect within this site, never to an address supplied by the form.
    nxt = request.form.get("next", "/")
    return redirect(nxt if nxt.startswith("/") and not urlparse(nxt).netloc else "/")


@bp.route("/notes")
def index():
    """List the newest notes."""
    return render_template("notes.html", notes=db.recent_notes())
