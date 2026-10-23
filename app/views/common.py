"""Helpers shared by every view: shared filters, the analysis object, charts and instance identity.

What it does:
    * Reads the shared filters (importer, product, supplier, event) from the URL,
      so every page uses the same filter bar and links keep the user's choices.
    * Builds the "analysis" dict every page renders: summary sentences, charts,
      tables and source links. The same dict is what "Save analysis" stores in S3,
      which is why a saved analysis reopens identically (Feature 3).
    * Finds this server's EC2 instance ID and AZ once at start, for the page footer
      (load-balancing test: "show instance ID on page").

Inputs:
    Flask request arguments; EC2 instance metadata.

Outputs:
    Plain dicts for templates.

How to run:
    Not run directly.
"""

from __future__ import annotations

import functools
import json
import math
from typing import Any

import pandas as pd
import requests
from flask import request

DEFAULT_HS6 = "845020"  # washing machines over 10 kg: the brief's known case
CHART_COLOURS = ["#1f6feb", "#d1495b", "#2a9d8f", "#e9a03b", "#6f42c1", "#5c6b73", "#8ab17d", "#b5838d"]


@functools.lru_cache(maxsize=1)
def instance_identity() -> dict[str, str]:
    """Return {"instance_id", "az"} from EC2 metadata (IMDSv2), or "local" off EC2."""
    base = "http://169.254.169.254/latest"
    try:
        token = requests.put(
            f"{base}/api/token", headers={"X-aws-ec2-metadata-token-ttl-seconds": "300"}, timeout=1
        ).text
        head = {"X-aws-ec2-metadata-token": token}
        return {
            "instance_id": requests.get(f"{base}/meta-data/instance-id", headers=head, timeout=1).text,
            "az": requests.get(f"{base}/meta-data/placement/availability-zone", headers=head, timeout=1).text,
        }
    except requests.RequestException:
        return {"instance_id": "local", "az": "local"}


def filters() -> dict[str, str]:
    """Shared filter values from the query string, with defaults."""
    return {
        "importer": request.args.get("importer", "US").upper()[:3],
        "hs6": "".join(ch for ch in request.args.get("hs6", DEFAULT_HS6) if ch.isdigit())[:6] or DEFAULT_HS6,
        "supplier": request.args.get("supplier", "").upper()[:3],
        "event_id": request.args.get("event_id", ""),
    }


def clean(value: Any) -> Any:
    """Make a value JSON-safe: NaN becomes None, numpy numbers become Python numbers."""
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
        if isinstance(value, float) and math.isnan(value):
            return None
    return value


def records(df: pd.DataFrame, columns: list[str] | None = None) -> list[dict[str, Any]]:
    """DataFrame rows as JSON-safe dicts (for tables and saved analyses)."""
    if df is None or df.empty:
        return []
    df = df[columns] if columns else df
    return [{k: clean(v) for k, v in row.items()} for row in df.to_dict("records")]


def line_chart(chart_id: str, title: str, pivot: pd.DataFrame, y_format: str, marks: list[dict] | None = None) -> dict:
    """Build a line-chart spec from a pivot table (index = months, columns = series).

    Args:
        chart_id: HTML id for the canvas.
        title: Chart title.
        pivot: Rows are months (YYYY-MM), columns are series names.
        y_format: "usd_m", "pct" or "hhi", used for axis ticks and tooltips.
        marks: Optional vertical event markers [{"month": "2018-07", "label": "List 1"}].

    Returns:
        A dict the front-end turns into a Chart.js chart.
    """
    datasets = []
    for i, col in enumerate(pivot.columns):
        datasets.append(
            {
                "label": str(col),
                "data": [clean(v) for v in pivot[col].tolist()],
                "color": CHART_COLOURS[i % len(CHART_COLOURS)],
            }
        )
    return {
        "id": chart_id,
        "type": "line",
        "title": title,
        "labels": list(pivot.index),
        "datasets": datasets,
        "y_format": y_format,
        "marks": marks or [],
    }


def bar_chart(chart_id: str, title: str, labels: list[str], values: list[float], y_format: str) -> dict:
    """Build a horizontal bar-chart spec (used for top movers)."""
    return {
        "id": chart_id,
        "type": "bar",
        "title": title,
        "labels": labels,
        "datasets": [{"label": title, "data": [clean(v) for v in values], "color": CHART_COLOURS[0]}],
        "y_format": y_format,
        "marks": [],
    }


def analysis(
    view: str,
    title: str,
    params: dict,
    meta: dict,
    summary: list[str],
    charts: list[dict],
    tables: list[dict],
    sources: list[dict],
) -> dict[str, Any]:
    """Assemble the analysis dict that pages render and "Save analysis" stores.

    Args:
        view: Page name, e.g. "explorer".
        title: Heading for the analysis.
        params: The inputs the user chose (shown under "Inputs").
        meta: Search metadata: hs6, importer, supplier, event_id (Feature 5).
        summary: Plain-language sentences (Feature 1).
        charts: Chart specs from line_chart / bar_chart.
        tables: [{"title", "columns": [{"key", "label", "format"}], "rows"}].
        sources: [{"label", "url"}] links to the data and legal sources.

    Returns:
        The analysis dict.
    """
    return {
        "view": view,
        "title": title,
        "params": params,
        "meta": meta,
        "summary": summary,
        "charts": charts,
        "tables": tables,
        "sources": sources,
    }


def analysis_json(a: dict[str, Any]) -> str:
    """Serialise an analysis for the hidden "Save analysis" form field."""
    return json.dumps(a, default=str)


def event_marks(events: list[dict], months: list[str]) -> list[dict]:
    """Vertical chart markers for tariff events that fall inside the chart's months."""
    if not months:
        return []
    return [
        {"month": str(e["effective_date"])[:7], "label": e["event_id"].replace("_", " ")}
        for e in events
        if months[0] <= str(e["effective_date"])[:7] <= months[-1]
    ]
