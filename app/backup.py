"""Export and import saved analyses and notes as one zip file.

What it does:
    The AWS Academy Sandbox deletes everything at the end of a session, including
    the saved analyses (S3) and notes (RDS) of Features 3 and 4. This module packs
    them into one zip a user can download to their laptop, and loads that zip back
    into a fresh stack. The same zip, shipped in the data snapshot, puts a few demo
    analyses and notes on the History page of every new stack.

    Importing is idempotent: an analysis whose ID already exists, or an identical
    note, is skipped, so importing the same file twice changes nothing.

Inputs:
    export: the analyses and notes tables, and the Markdown files in storage.
    import: zip bytes made by export_bundle().

Outputs:
    export: zip bytes (manifest.json, analyses.json, notes.json, analyses/...md).
    import: counts of what was added.

How to run:
    Not run directly. Used by app/views/history.py (Export/Import buttons) and
    batch/load_demo.py (demo content in new stacks).
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from batch.storage_io import Store
from config.settings import settings

FORMAT_VERSION = 1
MAX_UNCOMPRESSED = 50 * 1024 * 1024  # refuse zips that expand beyond 50 MB
ANALYSIS_COLUMNS = [
    "id",
    "title",
    "view",
    "s3_key",
    "hs6",
    "importer",
    "supplier",
    "event_id",
    "params",
    "created_at",
    "instance_id",
]
NOTE_COLUMNS = [
    "target_type",
    "target_id",
    "hs6",
    "importer",
    "supplier",
    "event_id",
    "body",
    "created_at",
    "instance_id",
]


def _json_default(value: Any) -> str:
    """Write dates and UUIDs as text in the export."""
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def export_bundle(conn, store: Store) -> bytes:
    """Pack every saved analysis (metadata + Markdown) and every note into a zip.

    Args:
        conn: Open database connection.
        store: Storage holding the analysis Markdown files.

    Returns:
        The zip file as bytes.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        analyses = cur.execute(f"SELECT {', '.join(ANALYSIS_COLUMNS)} FROM analyses ORDER BY created_at").fetchall()
        notes = cur.execute(f"SELECT {', '.join(NOTE_COLUMNS)} FROM notes ORDER BY created_at").fetchall()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "manifest.json",
            json.dumps(
                {
                    "format": FORMAT_VERSION,
                    "app": "TradeShift",
                    "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "analyses": len(analyses),
                    "notes": len(notes),
                },
                indent=2,
            ),
        )
        z.writestr("analyses.json", json.dumps(analyses, default=_json_default, indent=2))
        z.writestr("notes.json", json.dumps(notes, default=_json_default, indent=2))
        for a in analyses:
            if store.exists(a["s3_key"]):
                z.writestr(a["s3_key"], store.read_bytes(a["s3_key"]))
    return buf.getvalue()


def _check_zip(z: zipfile.ZipFile) -> None:
    """Reject files that are not TradeShift exports or that are unreasonably large."""
    names = set(z.namelist())
    if not {"manifest.json", "analyses.json", "notes.json"} <= names:
        raise ValueError("This is not a TradeShift export (manifest.json, analyses.json or notes.json missing).")
    if sum(i.file_size for i in z.infolist()) > MAX_UNCOMPRESSED:
        raise ValueError("The export is too large to import.")
    for name in names - {"manifest.json", "analyses.json", "notes.json"}:
        # Only Markdown files under the analyses/ prefix, never paths that climb out of it.
        if not name.startswith(settings.analyses_prefix) or ".." in name.split("/") or not name.endswith(".md"):
            raise ValueError(f"Unexpected file in the export: {name}")


def import_bundle(conn, store: Store, data: bytes) -> dict[str, int]:
    """Load a zip made by export_bundle() into the database and storage.

    Args:
        conn: Open database connection (committed here).
        store: Storage to write the analysis Markdown files to.
        data: The zip file's bytes.

    Returns:
        {"analyses": added, "notes": added, "skipped": already present}.
    """
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("The file is not a zip file.") from exc
    _check_zip(z)
    analyses = json.loads(z.read("analyses.json"))
    notes = json.loads(z.read("notes.json"))
    names = set(z.namelist())
    added_a = added_n = skipped = 0
    with conn.cursor() as cur:
        for a in analyses:
            if a["s3_key"] not in names:
                skipped += 1  # metadata without its file cannot be reopened
                continue
            cur.execute(
                f"""INSERT INTO analyses ({', '.join(ANALYSIS_COLUMNS)})
                    VALUES ({', '.join(['%s'] * len(ANALYSIS_COLUMNS))}) ON CONFLICT (id) DO NOTHING""",
                [Jsonb(a.get("params") or {}) if c == "params" else a.get(c) for c in ANALYSIS_COLUMNS],
            )
            if cur.rowcount:
                store.write_bytes(a["s3_key"], z.read(a["s3_key"]))
                added_a += 1
            else:
                skipped += 1
        for n in notes:
            # A note is "the same" if target, text and time all match.
            cur.execute(
                f"""INSERT INTO notes ({', '.join(NOTE_COLUMNS)})
                    SELECT {', '.join(['%s'] * len(NOTE_COLUMNS))}
                    WHERE NOT EXISTS (SELECT 1 FROM notes WHERE target_type=%s AND target_id=%s
                                      AND body=%s AND created_at=%s)""",
                [n.get(c) for c in NOTE_COLUMNS] + [n["target_type"], n["target_id"], n["body"], n["created_at"]],
            )
            added_n += cur.rowcount
            skipped += 1 - cur.rowcount
    conn.commit()
    return {"analyses": added_a, "notes": added_n, "skipped": skipped}
