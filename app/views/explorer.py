"""Corridor explorer: import value and market share by importer, supplier and HS6 product.

What it does:
    For one importer and product, shows monthly import value and each supplier's
    share (optionally smoothed with a 12-month rolling average), the latest-year
    share table, the tariff events that cover the product, and the product's notes.
    (Extra feature, "Corridor explorer"; target: chart loads in under 3 seconds.)

Inputs:
    Query string: importer, hs6, supplier (optional, highlights one), smooth (0/1).

Outputs:
    The explorer page; JSON product search for the filter bar at /api/products.

How to run:
    Registered by app/app.py at /explorer.
"""

from __future__ import annotations

import pandas as pd
from flask import Blueprint, jsonify, render_template, request

from app import db
from app.formatting import month_label
from app.views.common import analysis, event_marks, filters, line_chart, records

bp = Blueprint("explorer", __name__)

SHOWN_SUPPLIERS = 6  # more lines than this make the chart unreadable


def supplier_table(trade: pd.DataFrame) -> pd.DataFrame:
    """Latest 12 months vs the 12 before: value, share and growth per supplier.

    Args:
        trade: Monthly rows (supplier, month, value_usd) for one product.

    Returns:
        One row per supplier, largest first.
    """
    months = sorted(trade["month"].unique())
    last, prev = months[-12:], months[-24:-12]
    cur = trade[trade["month"].isin(last)].groupby("supplier")["value_usd"].sum()
    old = trade[trade["month"].isin(prev)].groupby("supplier")["value_usd"].sum()
    out = pd.DataFrame({"value_last12": cur, "value_prev12": old}).fillna(0)
    out["share_last12"] = 100 * out["value_last12"] / out["value_last12"].sum()
    out["share_prev12"] = 100 * out["value_prev12"] / max(out["value_prev12"].sum(), 1)
    out["share_change"] = out["share_last12"] - out["share_prev12"]
    out["growth"] = 100 * (out["value_last12"] / out["value_prev12"].where(out["value_prev12"] > 0) - 1)
    return out.sort_values("value_last12", ascending=False).reset_index()


def build(f: dict[str, str], smooth: bool) -> dict:
    """Build the explorer analysis for one importer and product.

    Args:
        f: Shared filters (importer, hs6, supplier, event_id).
        smooth: Apply a 12-month rolling average to shares.

    Returns:
        The analysis dict (see app/views/common.py).
    """
    names = db.countries()
    prod = db.product(f["hs6"]) or {"hs6": f["hs6"], "description": "unknown product"}
    trade = db.trade_series(f["importer"], f["hs6"])
    events = db.product_events(f["hs6"])
    title = (
        f"{names.get(f['importer'], f['importer'])} imports of HS {f['hs6'][:4]}.{f['hs6'][4:]} ({prod['description']})"
    )
    if trade.empty:
        return analysis("explorer", title, f, f, ["No imports recorded for this product and importer."], [], [], [])

    value = trade.pivot_table(index="month", columns="supplier", values="value_usd", aggfunc="sum").fillna(0)
    share = 100 * value.div(value.sum(axis=1), axis=0)
    if smooth:
        # 12-month rolling average removes seasonality (Methodology 4.1).
        share = share.rolling(12, min_periods=12).mean()
    top = value.sum().sort_values(ascending=False).index[:SHOWN_SUPPLIERS].tolist()
    if f["supplier"] and f["supplier"] in value.columns and f["supplier"] not in top:
        top.append(f["supplier"])
    rename = {c: names.get(c, c) for c in value.columns}
    months = list(value.index)

    table = supplier_table(trade)
    table["name"] = table["supplier"].map(lambda c: names.get(c, c))
    total_last, total_prev = table["value_last12"].sum(), table["value_prev12"].sum()
    leader = table.iloc[0]
    summary = [
        f"In the latest 12 months ({month_label(months[-12])} to {month_label(months[-1])}), {title.split(' (')[0]} were "
        f"US${total_last / 1e6:,.1f}m, {'up' if total_last >= total_prev else 'down'} "
        f"{abs(100 * (total_last / total_prev - 1)) if total_prev else 0:,.1f}% on the year before.",
        f"{leader['name']} is the largest supplier with {leader['share_last12']:.1f}% of the market "
        f"({leader['share_change']:+.1f} pts on the year before).",
    ]
    charts = [
        line_chart(
            "value",
            "Import value by supplier (US$ millions)",
            value[top].rename(columns=rename),
            "usd_m",
            event_marks(events, months),
        ),
        line_chart(
            "share",
            "Market share by supplier (%)" + (" — 12-month average" if smooth else ""),
            share[top].rename(columns=rename),
            "pct",
            event_marks(events, months),
        ),
    ]
    tables = [
        {
            "title": "Suppliers: latest 12 months vs previous 12",
            "columns": [
                {"key": "name", "label": "Supplier"},
                {"key": "value_last12", "label": "Value, last 12m", "format": "usd_m"},
                {"key": "share_last12", "label": "Share, last 12m", "format": "pct"},
                {"key": "share_prev12", "label": "Share, previous 12m", "format": "pct"},
                {"key": "share_change", "label": "Change", "format": "pts"},
                {"key": "growth", "label": "Value growth", "format": "signed_pct"},
            ],
            "rows": records(table.head(15)),
        }
    ]
    if events:
        tables.append(
            {
                "title": "Tariff events covering this product",
                "columns": [
                    {"key": "name", "label": "Event"},
                    {"key": "effective_date", "label": "Effective", "format": "month"},
                ],
                "rows": [{"name": e["name"], "effective_date": str(e["effective_date"])} for e in events],
            }
        )
    sources = [
        {
            "label": "US Census international trade API (imports by HS6 and country)",
            "url": f"/source/explorer/{f['hs6']}?importer={f['importer']}",
        }
    ]
    sources += [{"label": e["name"], "url": e["source_url"]} for e in events]
    params = {"importer": f["importer"], "hs6": f["hs6"], "supplier": f["supplier"], "smooth": smooth}
    return analysis("explorer", title, params, {**f, "event_id": ""}, summary, charts, tables, sources)


@bp.route("/explorer")
def page():
    """Render the explorer for the filters in the URL."""
    f = filters()
    smooth = request.args.get("smooth", "1") == "1"
    a = build(f, smooth)
    return render_template(
        "explorer.html", a=a, f=f, smooth=smooth, importers=db.importers(), notes=db.notes_for("product", f["hs6"])
    )


@bp.route("/api/products")
def products_api():
    """JSON product search used by the filter bar's product box."""
    q = request.args.get("q", "")
    return jsonify(db.search_products(q) if len(q) >= 2 else [])
