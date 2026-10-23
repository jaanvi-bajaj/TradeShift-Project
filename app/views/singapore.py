"""Singapore lens: products where Singapore's re-exports to the US grew after the tariffs.

What it does:
    Shows total monthly Singapore re-exports (RX) and domestic exports (DX) to the
    US, a chosen product's RX/DX series, and the flagged products: re-exports up by
    at least SG_MIN_GROWTH_PCT after the first Section 301 list that covered them.
    The page states that this is growth in Singapore's hub role, not proof of
    transshipment (Methodology 4.6).

Inputs:
    Query string: hs6 (optional product to chart), all (1 = show unflagged too).

Outputs:
    The Singapore lens page.

How to run:
    Registered by app/app.py at /singapore.
"""

from __future__ import annotations

from flask import Blueprint, render_template, request

from app import db
from app.formatting import product_label
from app.views.common import analysis, filters, line_chart, records
from config.settings import settings

bp = Blueprint("singapore", __name__)

ESTIMATE_NOTE = (
    "Re-exports by product are estimated: Singapore's exports to the US minus US imports of Singapore-origin goods. "
    "No free source splits Singapore's re-exports by HS6 product; the chart compares our total with SingStat's "
    "official figure."
)
HUB_NOTE = (
    "US data records country of origin, so goods re-exported through Singapore are still counted under their "
    "origin. Growth in re-exports shows Singapore's role as a hub growing; it is not proof of transshipment."
)


@bp.route("/singapore")
def page():
    """Render the Singapore lens."""
    f = filters()
    show_all = request.args.get("all") == "1"
    hs6 = request.args.get("hs6", "")
    lens = db.singapore_lens(flagged_only=not show_all, limit=50)
    totals = db.singapore_totals()
    charts, summary = [], []
    if not totals.empty:
        pivot = totals.set_index("month")[["rx_usd", "dx_usd", "est_rx_usd"]].rename(
            columns={
                "rx_usd": "Re-exports (SingStat, official)",
                "dx_usd": "Domestic exports (SingStat, official)",
                "est_rx_usd": "Re-exports, sum of our HS6 estimates",
            }
        )
        charts.append(
            line_chart(
                "sg_total",
                "Singapore exports to the US, all products (US$ millions)",
                pivot,
                "usd_m",
                [{"month": "2018-07", "label": "S301 List 1"}],
            )
        )
    if not lens.empty:
        if not hs6:
            hs6 = lens.iloc[0]["hs6"]
        flagged = int(lens["flagged"].sum())
        summary.append(
            f"{flagged} products tariffed under Section 301 show estimated Singapore re-exports to the US up at least "
            f"{settings.sg_min_growth_pct:g}% after the tariff, with at least "
            f"US${settings.sg_min_value_usd / 1e6:g}m of re-exports a year afterwards."
        )
        lens["product"] = [product_label(h, d, 50) for h, d in zip(lens["hs6"], lens["description"])]
        lens["cn_change"] = 100 * (lens["cn_share_after"] - lens["cn_share_before"])
    summary.append(ESTIMATE_NOTE)
    summary.append(HUB_NOTE)
    if hs6:
        series = db.singapore_product(hs6)
        if not series.empty:
            p = series.set_index("month")[["sg_exports_usd", "us_imports_sg_origin_usd", "est_reexports_usd"]].rename(
                columns={
                    "sg_exports_usd": "Singapore's exports to the US",
                    "us_imports_sg_origin_usd": "US imports of Singapore-origin goods",
                    "est_reexports_usd": "Estimated re-exports",
                }
            )
            charts.append(
                line_chart("sg_product", f"HS {hs6[:4]}.{hs6[4:]}: Singapore to the US (US$ millions)", p, "usd_m")
            )
    table = {
        "title": "Products with growing Singapore re-exports to the US (estimated)",
        "columns": [
            {"key": "product", "label": "Product"},
            {"key": "event_id", "label": "First tariff list"},
            {"key": "est_rx_before", "label": "Re-exports, 12m before", "format": "usd_m"},
            {"key": "est_rx_after", "label": "Re-exports, 12m after", "format": "usd_m"},
            {"key": "est_rx_growth_pct", "label": "Growth", "format": "signed_pct"},
            {"key": "est_rx_share_after_pct", "label": "Re-exports as share of SG exports", "format": "pct"},
            {"key": "cn_change", "label": "China's US share change", "format": "pts"},
        ],
        "rows": records(lens) if not lens.empty else [],
        "sg_links": True,
    }
    sources = [
        {"label": "UN Comtrade: Singapore's exports to the USA by HS6", "url": "https://comtradeplus.un.org/"},
        {
            "label": "SingStat: Re-Exports By Region And Market (M451511)",
            "url": "https://tablebuilder.singstat.gov.sg/table/TS/M451511",
        },
        {
            "label": "SingStat: Domestic Exports By Region And Market (M451501)",
            "url": "https://tablebuilder.singstat.gov.sg/table/TS/M451501",
        },
    ]
    a = analysis(
        "singapore",
        "Singapore lens: re-exports to the US after the tariffs",
        {"hs6": hs6, "all": show_all},
        {"hs6": hs6, "importer": "US", "supplier": "SG", "event_id": ""},
        summary,
        charts,
        [table],
        sources,
    )
    return render_template("singapore.html", a=a, f=f, show_all=show_all)
