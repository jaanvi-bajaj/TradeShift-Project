"""Save previous analysis (Feature 3): save the current view to S3, list and reopen saved ones.

What it does:
    POST /history/save takes the analysis dict the page embedded in its form,
    writes it to S3 as Markdown (app/storage.py) and records its metadata in RDS
    (app/db.py), so the Search page can find it. /history lists saved analyses,
    newest first; /history/<id> reopens one exactly as saved, with its notes;
    /history/<id>/download returns the Markdown file.

Inputs:
    Form field "analysis" (JSON) and optional "title".

Outputs:
    Markdown in S3, a row in the analyses table, and the history pages.

How to run:
    Registered by app/app.py.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from flask import Blueprint, Response, abort, redirect, render_template, request, url_for

from app import backup, db, storage
from app.views.common import instance_identity
from batch.storage_io import store

bp = Blueprint("history", __name__)

MAX_IMPORT = 20 * 1024 * 1024  # bytes; an export with dozens of analyses is well under 1 MB
MAX_PAYLOAD = 2_000_000  # bytes; a saved analysis is normally well under 200 KB


@bp.route("/history/save", methods=["POST"])
def save():
    """Save the posted analysis and go to its saved page."""
    raw = request.form.get("analysis", "")
    if not raw or len(raw) > MAX_PAYLOAD:
        abort(400, "No analysis to save")
    try:
        analysis = json.loads(raw)
    except json.JSONDecodeError:
        abort(400, "Analysis is not valid JSON")
    title = (request.form.get("title") or analysis.get("title") or "Untitled analysis").strip()[:200]
    analysis["title"] = title
    analysis_id = str(uuid.uuid4())
    key = storage.save(analysis, analysis_id)
    db.insert_analysis(
        title,
        analysis.get("view", "unknown"),
        key,
        analysis.get("meta", {}),
        analysis.get("params", {}),
        instance_identity()["instance_id"],
        analysis_id,
    )
    return redirect(url_for("history.show", analysis_id=analysis_id, saved=1))


@bp.route("/history")
def index():
    """List saved analyses, with the Export and Import buttons."""
    return render_template(
        "history.html",
        analyses=db.list_analyses(),
        imported=request.args.get("imported"),
        error=request.args.get("error"),
    )


@bp.route("/history/export")
def export():
    """Download every saved analysis and note as one zip, to keep across Sandbox sessions."""
    data = backup.export_bundle(db.conn(), store)
    name = f"tradeshift-export-{datetime.now(UTC):%Y%m%d-%H%M}.zip"
    return Response(data, mimetype="application/zip", headers={"Content-Disposition": f"attachment; filename={name}"})


@bp.route("/history/import", methods=["POST"])
def import_():
    """Load a zip made by Export: adds analyses and notes that are not here yet."""
    upload = request.files.get("bundle")
    data = upload.read(MAX_IMPORT + 1) if upload else b""
    if not data or len(data) > MAX_IMPORT:
        return redirect(url_for("history.index", error="Choose a TradeShift export file (zip, under 20 MB)."))
    try:
        result = backup.import_bundle(db.conn(), store, data)
    except ValueError as exc:
        return redirect(url_for("history.index", error=str(exc)))
    summary = f"{result['analyses']} analyses and {result['notes']} notes added, {result['skipped']} already here."
    return redirect(url_for("history.index", imported=summary))


@bp.route("/history/<analysis_id>")
def show(analysis_id: str):
    """Reopen one saved analysis from S3."""
    row = db.get_analysis(analysis_id) or abort(404)
    analysis, _ = storage.load(row["s3_key"])
    return render_template(
        "saved.html",
        a=analysis,
        row=row,
        notes=db.notes_for("analysis", analysis_id),
        just_saved=request.args.get("saved") == "1",
    )


@bp.route("/history/<analysis_id>/download")
def download(analysis_id: str):
    """Download the saved analysis as a Markdown file."""
    row = db.get_analysis(analysis_id) or abort(404)
    _, text = storage.load(row["s3_key"])
    return Response(
        text,
        mimetype="text/markdown",
        headers={"Content-Disposition": f"attachment; filename=tradeshift-{analysis_id[:8]}.md"},
    )
