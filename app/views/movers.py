"""Top movers: the biggest share shifts by value redirected, each with one sentence.

What it does:
    Lists the top 20 detector flags (default thresholds) ranked by value
    redirected, across all events or for one event. Each shows its plain-language
    sentence and the change in total imports, so readers can separate diversion
    (other suppliers gain) from trade destruction (the market shrinks)
    (Methodology 4.5).

Inputs:
    Query string: event_id ("" = all events), n (how many, default 20).

Outputs:
    The top movers page.

How to run:
    Registered by app/app.py at /movers.
"""

from __future__ import annotations

from flask import Blueprint, render_template, request

from app import db
from app.formatting import product_label
from app.views.common import analysis, bar_chart, filters, records
from batch.detector import DESTRUCTION_PCT
from config.settings import settings

bp = Blueprint("movers", __name__)


@bp.route("/movers")
def page():
    """Render the top movers list."""
    f = filters()
    event_id = request.args.get("event_id", "")
    n = min(int(request.args.get("n", settings.top_movers) or settings.top_movers), 100)
    names = db.countries()
    sig = db.signals(event_id or None, limit=n)
    title = "Top movers" + (f": {event_id.replace('_', ' ')}" if event_id else ": all tariff events")
    summary, charts, rows = [], [], []
    if not sig.empty:
        sig["product"] = [product_label(h, d) for h, d in zip(sig["hs6"], sig["description"])]
        sig["pair"] = [f"{names.get(a, a)} → {names.get(b, b)}" for a, b in zip(sig["loser"], sig["gainer"])]
        sig["share_lost"] = -sig["drop_pp"]  # shown as a fall, e.g. -39.3 pts
        total = sig["value_redirected_usd"].sum()
        destroyed = int((sig["pattern"] != "diversion").sum())
        summary = [
            f"The top {len(sig)} shifts redirected about US${total / 1e6:,.0f}m a year of imports between suppliers.",
            f"{destroyed} of them also show total imports falling by {abs(DESTRUCTION_PCT):g}% or more, so part of the lost share is "
            "trade destruction rather than diversion.",
        ]
        charts = [
            bar_chart(
                "movers",
                "Value redirected (US$ millions a year)",
                sig["product"].str[:28].tolist(),
                sig["value_redirected_usd"].tolist(),
                "usd_m",
            )
        ]
        rows = records(sig)
    table = {
        "title": "Top movers by value redirected",
        "columns": [
            {"key": "product", "label": "Product"},
            {"key": "pair", "label": "From → to"},
            {"key": "value_redirected_usd", "label": "Value redirected", "format": "usd_m"},
            {"key": "share_lost", "label": "Share lost", "format": "pts"},
            {"key": "gain_pp", "label": "Share gained", "format": "pts"},
            {"key": "total_change_pct", "label": "Total imports", "format": "signed_pct"},
            {"key": "pattern", "label": "Pattern"},
            {"key": "confidence", "label": "Confidence"},
            {"key": "explanation", "label": "Summary"},
        ],
        "rows": rows,
        "links": True,
    }
    a = analysis(
        "movers",
        title,
        {"event_id": event_id, "n": n},
        {"hs6": "", "importer": "US", "supplier": "", "event_id": event_id},
        summary,
        charts,
        [table],
        [],
    )
    return render_template("movers.html", a=a, f=f, event_id=event_id, events=db.events(), n=n)
