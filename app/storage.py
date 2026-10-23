"""Save and reopen analyses as Markdown files in S3 (Feature 3).

What it does:
    A saved analysis is one Markdown file: a readable report (title, inputs,
    summary, tables) followed by a fenced JSON block holding the exact inputs,
    results and chart data. Reopening reads that JSON block and renders it with
    the same template as the live page, so it looks identical, even after a
    restart or on a different server.

    Why S3, not EBS: an EBS volume attaches to one instance, so with auto scaling
    each web server would see different files. S3 is shared by all of them.

Inputs:
    An analysis dict built by a view (see app/views/common.py).

Outputs:
    analyses/YYYY/MM/<id>.md in the S3 bucket (or LOCAL_DATA_DIR when local).

How to run:
    Not run directly; used by app/views/history.py.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from app.formatting import FILTERS
from batch.storage_io import store
from config.settings import settings

DATA_FENCE = "```json tradeshift-analysis"
DATA_RE = re.compile(r"```json tradeshift-analysis\n(.*?)\n```", re.S)


def analysis_key(analysis_id: str, when: datetime) -> str:
    """Return the S3 key for a saved analysis, grouped by year and month."""
    return f"{settings.analyses_prefix}{when:%Y/%m}/{analysis_id}.md"


def to_markdown(analysis: dict[str, Any], saved_at: datetime) -> str:
    """Render an analysis as a Markdown report with its data embedded.

    Args:
        analysis: The analysis dict (title, params, summary, tables, charts, meta).
        saved_at: Save time, shown in the report.

    Returns:
        Markdown text.
    """
    lines = [f"# {analysis['title']}", "", f"Saved {saved_at:%d %b %Y %H:%M} UTC from the {analysis['view']} view.", ""]
    if analysis.get("params"):
        lines += ["## Inputs", ""] + [f"- **{k}**: {v}" for k, v in analysis["params"].items()] + [""]
    if analysis.get("summary"):
        lines += ["## Summary", ""] + [f"- {s}" for s in analysis["summary"]] + [""]
    for table in analysis.get("tables", []):
        cols = table["columns"]
        lines += [
            f"## {table['title']}",
            "",
            "| " + " | ".join(c["label"] for c in cols) + " |",
            "|" + "---|" * len(cols),
        ]
        for row in table["rows"]:
            cells = [
                FILTERS.get(c.get("format"), str)(row.get(c["key"])) if c.get("format") else str(row.get(c["key"], ""))
                for c in cols
            ]
            lines.append("| " + " | ".join(cell.replace("|", "/") for cell in cells) + " |")
        lines.append("")
    for source in analysis.get("sources", []):
        lines.append(f"- Source: [{source['label']}]({source['url']})")
    # The data block lets the app reopen the analysis exactly as it was saved.
    lines += [
        "",
        "<!-- Data used by TradeShift to reopen this analysis. -->",
        DATA_FENCE,
        json.dumps(analysis, default=str),
        "```",
        "",
    ]
    return "\n".join(lines)


def save(analysis: dict[str, Any], analysis_id: str) -> str:
    """Write an analysis to storage.

    Args:
        analysis: The analysis dict.
        analysis_id: UUID string used as the file name.

    Returns:
        The storage key written.
    """
    now = datetime.now(UTC)
    key = analysis_key(analysis_id, now)
    store.write_bytes(key, to_markdown(analysis, now).encode())
    return key


def load(key: str) -> tuple[dict[str, Any], str]:
    """Read a saved analysis.

    Args:
        key: Storage key from the analyses table.

    Returns:
        (the analysis dict, the full Markdown text).
    """
    text = store.read_bytes(key).decode()
    match = DATA_RE.search(text)
    if not match:
        raise ValueError(f"{key} has no TradeShift data block")
    return json.loads(match.group(1)), text
