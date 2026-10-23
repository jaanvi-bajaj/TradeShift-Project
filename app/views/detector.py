"""Diversion detector page, with threshold sliders, and the per-signal source pages.

What it does:
    /detector re-runs batch.detector.detect() on the stored before/after shares
    with the thresholds from the sliders, so users see flags appear and disappear
    as they change the rules (Extra feature, "Diversion detector"). Each flag has
    its plain-language summary, a confidence label from the quantity check, the
    legal source of the tariff and a link to its data source page. The event's
    difference-in-differences result is shown as a validation box.

    /source/<event_id>/<hs6> shows the exact Census query and the numbers behind
    a signal, from the database, so the source link works with no external call
    (Feature 1, "a link to its source query").

Inputs:
    Query string: event_id ("" = all events), min_drop, min_gain, min_value (US$ m),
    confidence ("" or "higher").

Outputs:
    The detector page and the source pages.

How to run:
    Registered by app/app.py.
"""

from __future__ import annotations

import pandas as pd
from flask import Blueprint, abort, render_template, request

from app import db
from app.formatting import month_label, product_label
from app.views.common import analysis, filters, records
from batch.detector import DESTRUCTION_PCT, Thresholds, detect
from batch.explain import explain_row
from batch.metrics import event_windows
from config.settings import settings

bp = Blueprint("detector", __name__)

SIGNAL_COLUMNS = [
    {"key": "product", "label": "Product"},
    {"key": "event_label", "label": "Event"},
    {"key": "loser_name", "label": "Lost share"},
    {"key": "loser_change", "label": "Share before → after"},
    {"key": "gainer_name", "label": "Gained share"},
    {"key": "gainer_change", "label": "Share before → after"},
    {"key": "value_redirected_usd", "label": "Value redirected", "format": "usd_m"},
    {"key": "total_change_pct", "label": "Total imports", "format": "signed_pct"},
    {"key": "confidence", "label": "Confidence"},
    {"key": "explanation", "label": "Summary"},
]


def thresholds_from_request() -> Thresholds:
    """Read slider values, falling back to the defaults in config/settings.py."""

    def num(name: str, default: float) -> float:
        try:
            return float(request.args.get(name, default))
        except ValueError:
            return default

    return Thresholds(
        min_drop_pp=num("min_drop", settings.min_drop_pp),
        min_gain_pp=num("min_gain", settings.min_gain_pp),
        min_annual_value_usd=num("min_value", settings.min_annual_value_usd / 1e6) * 1e6,
    )


def decorate(sig: pd.DataFrame, names: dict, descriptions: dict, events: pd.DataFrame) -> pd.DataFrame:
    """Add display columns (names, before→after text, summary sentence, links) to flags."""
    if sig.empty:
        return sig
    sig = sig.copy()
    sig["product"] = [product_label(h, descriptions.get(h)) for h in sig["hs6"]]
    sig["event_label"] = sig["event_id"].map(events["name"])
    sig["loser_name"] = sig["loser"].map(lambda c: names.get(c, c))
    sig["gainer_name"] = sig["gainer"].map(lambda c: names.get(c, c))
    sig["loser_change"] = [f"{a:.1f}% → {b:.1f}%" for a, b in zip(sig["loser_share_before"], sig["loser_share_after"])]
    sig["gainer_change"] = [
        f"{a:.1f}% → {b:.1f}%" for a, b in zip(sig["gainer_share_before"], sig["gainer_share_after"])
    ]
    sig["explanation"] = [explain_row(r, names, descriptions, events) for _, r in sig.iterrows()]
    sig["source_url"] = sig["event_id"].map(events["source_url"])
    sig["data_url"] = "/source/" + sig["event_id"] + "/" + sig["hs6"]
    return sig


DESTRUCTION_COLUMNS = [
    {"key": "product", "label": "Product"},
    {"key": "event_label", "label": "Event"},
    {"key": "total_before", "label": "Imports, 12m before", "format": "usd_m"},
    {"key": "total_after", "label": "Imports, 12m after", "format": "usd_m"},
    {"key": "total_change_pct", "label": "Change", "format": "signed_pct"},
    {"key": "biggest_loser", "label": "Largest share lost"},
]


def trade_destruction(products: pd.DataFrame, t: Thresholds, names: dict, events: pd.DataFrame) -> pd.DataFrame:
    """Covered products whose total imports fell by DESTRUCTION_PCT or more (Methodology 4.5).

    Why: when a tariff hits every big supplier (Section 201 washers in 2018), no
    untariffed supplier can gain, so the detector flags nothing; the fall in total
    imports is the real story.

    Args:
        products: event_products rows for the chosen event(s).
        t: Thresholds (the value floor applies here too).
        names: ISO code to country name.
        events: tariff_events indexed by event_id.

    Returns:
        Up to 50 products, largest absolute fall first, with display columns.
    """
    if products.empty:
        return pd.DataFrame()
    p = products[products["total_before"] >= t.min_annual_value_usd].copy()
    p["total_change_pct"] = 100 * (p["total_after"] / p["total_before"] - 1)
    p = p[p["total_change_pct"] <= DESTRUCTION_PCT]
    if p.empty:
        return p
    p["fall"] = p["total_before"] - p["total_after"]
    p = p.sort_values("fall", ascending=False).head(50)
    desc = {
        r["hs6"]: r["description"]
        for r in db.rows("SELECT hs6, description FROM products WHERE hs6 = ANY(%s)", (list(p["hs6"]),))
    }
    p["product"] = [product_label(h, desc.get(h)) for h in p["hs6"]]
    p["event_label"] = p["event_id"].map(events["name"])
    shares = db.frame(
        """SELECT DISTINCT ON (event_id, hs6) event_id, hs6, supplier, share_after - share_before AS chg
           FROM event_shares WHERE hs6 = ANY(%s) ORDER BY event_id, hs6, share_after - share_before""",
        (list(p["hs6"]),),
    )
    if not shares.empty:
        lose = {
            (r.event_id, r.hs6): f"{names.get(r.supplier, r.supplier)} ({100 * r.chg:+.1f} pts)"
            for r in shares.itertuples()
        }
        p["biggest_loser"] = [lose.get((e, h), "") for e, h in zip(p["event_id"], p["hs6"])]
    return p


@bp.route("/detector")
def page():
    """Run the detector with the chosen thresholds and render the flags."""
    f = filters()
    event_id = request.args.get("event_id", "S301_L1")
    only_higher = request.args.get("confidence", "") == "higher"
    t = thresholds_from_request()
    events = pd.DataFrame(db.events()).set_index("event_id")
    shares = db.event_shares(event_id or None)
    products = db.event_products(event_id or None)
    sig = detect(shares, products, t) if not shares.empty else pd.DataFrame()
    if only_higher and not sig.empty:
        sig = sig[sig["confidence"] == "higher"]
    names = db.countries()
    codes = list(sig["hs6"].unique()) if not sig.empty else []
    descriptions = {
        p["hs6"]: p["description"]
        for p in db.rows("SELECT hs6, description FROM products WHERE hs6 = ANY(%s)", (codes,))
    }
    sig = decorate(sig.head(300), names, descriptions, events)

    label = events.loc[event_id, "name"] if event_id in events.index else "all events"
    n_higher = int((sig["confidence"] == "higher").sum()) if not sig.empty else 0
    summary = [
        f"{len(sig)} product{'' if len(sig) == 1 else 's'} flagged for {label}: a tariffed supplier lost at least {t.min_drop_pp:g} points of "
        f"share and an untariffed supplier gained at least {t.min_gain_pp:g} points, among products with at "
        f"least US${t.min_annual_value_usd / 1e6:,.0f}m of annual imports.",
        f"{n_higher} of them are higher confidence: quantity shares moved the same way as value shares.",
    ]
    destruction = trade_destruction(products, t, names, events)
    if not destruction.empty:
        summary.append(
            f"{len(destruction)} covered product{'' if len(destruction) == 1 else 's'} saw total US imports fall by {abs(DESTRUCTION_PCT):g}% or more. "
            "Where every big supplier was tariffed, that is trade destruction (imports replaced or lost), not diversion."
        )
    did = db.did_results().get(event_id) if event_id else None
    sources = [{"label": label, "url": events.loc[event_id, "source_url"]}] if event_id in events.index else []
    a = analysis(
        "detector",
        f"Diversion detector: {label}",
        {
            "event_id": event_id,
            "min_drop_pp": t.min_drop_pp,
            "min_gain_pp": t.min_gain_pp,
            "min_value_usd_m": t.min_annual_value_usd / 1e6,
            "higher_confidence_only": only_higher,
        },
        {"hs6": "", "importer": "US", "supplier": "", "event_id": event_id},
        summary,
        [],
        [
            {"title": "Flagged products", "columns": SIGNAL_COLUMNS, "rows": records(sig), "links": True},
            {
                "title": "Trade destruction: total imports fell sharply",
                "columns": DESTRUCTION_COLUMNS,
                "rows": records(destruction),
                "hs_links": True,
            },
        ],
        sources,
    )
    return render_template(
        "detector.html",
        a=a,
        f=f,
        t=t,
        event_id=event_id,
        events=db.events(),
        did=did,
        only_higher=only_higher,
        defaults=settings,
    )


@bp.route("/source/<event_id>/<hs6>")
def source(event_id: str, hs6: str):
    """Show the data and query behind one signal (or one explorer product)."""
    names = db.countries()
    prod = db.product(hs6) or abort(404)
    importer = request.args.get("importer", "US")
    ev = next((e for e in db.events() if e["event_id"] == event_id), None)
    if ev:
        before, after = event_windows(str(ev["effective_date"]), settings.window_months, settings.lag_months)
        shares = db.frame(
            "SELECT * FROM event_shares WHERE event_id=%s AND hs6=%s ORDER BY share_before DESC", (event_id, hs6)
        )
        shares["name"] = shares["supplier"].map(lambda c: names.get(c, c)) if not shares.empty else []
        months = before + after
    else:
        before, after, shares = [], [], pd.DataFrame()
        months = []
    trade = db.trade_series(importer, hs6)
    if months:
        trade = trade[trade["month"].isin(months)]
    pivot = trade.pivot_table(index="month", columns="supplier", values="value_usd", aggfunc="sum").fillna(0)
    if not pivot.empty:
        pivot = pivot[pivot.sum().sort_values(ascending=False).index[:8]]
    first = months[0] if months else (pivot.index[0] if not pivot.empty else "")
    last = months[-1] if months else (pivot.index[-1] if not pivot.empty else "")
    query = (
        f"{settings.census_url}?get=CTY_CODE,CTY_NAME,I_COMMODITY,GEN_VAL_MO,GEN_QY1_MO,UNIT_QY1"
        f"&COMM_LVL=HS6&I_COMMODITY={hs6}&time=from+{first}+to+{last}&key=YOUR_CENSUS_KEY"
    )
    return render_template(
        "source.html",
        prod=prod,
        ev=ev,
        before=before,
        after=after,
        shares=records(shares),
        names=names,
        pivot=pivot,
        query=query,
        importer=importer,
        month_label=month_label,
    )
