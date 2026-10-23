"""Concentration score: HHI per product, before and after each tariff.

What it does:
    Shows one product's monthly HHI (and 12-month rolling HHI) with the tariff
    dates marked, the HHI before and after each event that covers it, and, for a
    chosen event, the products whose HHI changed most. A fall in HHI means
    sourcing diversified; a rise means dependence moved to a new dominant
    supplier (Methodology 4.2).

Inputs:
    Query string: importer, hs6, event_id.

Outputs:
    The concentration page.

How to run:
    Registered by app/app.py at /concentration.
"""

from __future__ import annotations

import pandas as pd
from flask import Blueprint, render_template, request

from app import db
from app.formatting import hhi as fmt_hhi
from app.formatting import product_label
from app.views.common import analysis, event_marks, filters, line_chart, records

bp = Blueprint("concentration", __name__)


def hhi_band(value: float) -> str:
    """US merger-guideline bands, as a plain-language label for an HHI value."""
    if value < 1500:
        return "unconcentrated"
    if value < 2500:
        return "moderately concentrated"
    return "highly concentrated"


@bp.route("/concentration")
def page():
    """Render HHI for one product and the biggest HHI changes for one event."""
    f = filters()
    event_id = request.args.get("event_id", "S301_L1")
    names = db.countries()
    prod = db.product(f["hs6"]) or {"description": "unknown product"}
    series = db.hhi_series(f["importer"], f["hs6"])
    events = db.product_events(f["hs6"])
    title = f"Supplier concentration (HHI): HS {f['hs6'][:4]}.{f['hs6'][4:]} {prod['description']}, {names.get(f['importer'], f['importer'])}"

    charts, summary, tables = [], [], []
    if not series.empty:
        pivot = series.set_index("month")[["hhi", "hhi_12m"]].rename(
            columns={"hhi": "HHI (monthly)", "hhi_12m": "HHI (12-month average)"}
        )
        charts.append(line_chart("hhi", "HHI, 0 to 10,000", pivot, "hhi", event_marks(events, list(pivot.index))))
        latest = series.dropna(subset=["hhi_12m"]).iloc[-1] if series["hhi_12m"].notna().any() else series.iloc[-1]
        summary.append(
            f"The 12-month average HHI is now {fmt_hhi(latest['hhi_12m'])}, which is "
            f"{hhi_band(latest['hhi_12m'] or 0)} ({int(latest['n_suppliers'])} named suppliers in the latest month)."
        )

    rows = []
    for e in events:
        ep = db.event_product(e["event_id"], f["hs6"])
        if ep:
            rows.append(
                {
                    "event": e["name"],
                    "hhi_before": ep["hhi_before"],
                    "hhi_after": ep["hhi_after"],
                    "change": ep["hhi_after"] - ep["hhi_before"],
                }
            )
            direction = "fell" if ep["hhi_after"] < ep["hhi_before"] else "rose"
            meaning = "sourcing diversified" if direction == "fell" else "dependence moved towards fewer suppliers"
            summary.append(
                f"Around the {e['name']} tariff, HHI {direction} from {fmt_hhi(ep['hhi_before'])} to "
                f"{fmt_hhi(ep['hhi_after'])} ({meaning})."
            )
    if rows:
        tables.append(
            {
                "title": "HHI before and after each tariff event",
                "columns": [
                    {"key": "event", "label": "Event"},
                    {"key": "hhi_before", "label": "HHI before", "format": "hhi"},
                    {"key": "hhi_after", "label": "HHI after", "format": "hhi"},
                    {"key": "change", "label": "Change", "format": "signed_hhi"},
                ],
                "rows": rows,
            }
        )

    movers = db.hhi_changes(event_id) if event_id else pd.DataFrame()
    if not movers.empty:
        movers["product"] = [product_label(h, d, 50) for h, d in zip(movers["hs6"], movers["description"])]
        tables.append(
            {
                "title": f"Largest HHI changes for {event_id.replace('_', ' ')} (US imports)",
                "columns": [
                    {"key": "product", "label": "Product"},
                    {"key": "hhi_before", "label": "HHI before", "format": "hhi"},
                    {"key": "hhi_after", "label": "HHI after", "format": "hhi"},
                    {"key": "hhi_change", "label": "Change", "format": "signed_hhi"},
                    {"key": "total_before", "label": "Imports before (12m)", "format": "usd_m"},
                ],
                "rows": records(movers),
                "hs_links": True,
            }
        )
    sources = [{"label": e["name"], "url": e["source_url"]} for e in events]
    a = analysis(
        "concentration",
        title,
        {**f, "event_id": event_id},
        {**f, "event_id": event_id},
        summary,
        charts,
        tables,
        sources,
    )
    return render_template(
        "concentration.html",
        a=a,
        f=f,
        event_id=event_id,
        events=db.events(),
        importers=db.importers(),
        notes=db.notes_for("product", f["hs6"]),
    )
