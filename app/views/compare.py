"""Comparison on a normalised basis (Feature 2): two suppliers, products or importers side by side.

What it does:
    Three modes, each comparing A with B on the same scale:
      * suppliers: two suppliers' share of one importer's market for one product
      * products:  two products in one importer's market (one supplier or all)
      * importers: one supplier's share of two importers' markets for one product
    For each side it shows market share, year-on-year growth, CAGR over the chosen
    years, and the HHI change, plus a chart of share (in %) and value indexed to
    100 at the start, so different-sized markets are comparable. Chart and table
    come from the same data, so they always load together.

Inputs:
    Query string: mode, a, b, importer, hs6, supplier, start (year), end (year).

Outputs:
    The comparison page.

How to run:
    Registered by app/app.py at /compare.
"""

from __future__ import annotations

import pandas as pd
from flask import Blueprint, render_template, request

from app import db
from app.views.common import analysis, filters, line_chart
from batch.metrics import cagr, yoy_growth

bp = Blueprint("compare", __name__)

DEFAULTS = {"suppliers": ("CN", "VN"), "products": ("845020", "845011"), "importers": ("US", "JP")}


def side(importer: str, hs6: str, supplier: str, start: str, end: str) -> tuple[pd.DataFrame, dict]:
    """Monthly series and summary numbers for one side of the comparison.

    Args:
        importer: Importer code.
        hs6: Product code.
        supplier: Supplier code, or "" for the whole market.
        start: First year (YYYY).
        end: Last year (YYYY).

    Returns:
        (monthly DataFrame with value, total and share, summary dict).
    """
    df = db.supplier_series(importer, supplier or "__ALL__", hs6)
    if df.empty:
        return df, {}
    df = df.set_index("month")
    df = df[(df.index >= f"{start}-01") & (df.index <= f"{end}-12")]
    df["value"] = df["supplier_value"].fillna(0) if supplier else df["total"]
    df["share"] = 100 * df["value"] / df["total"]
    annual = df["value"].groupby(df.index.str[:4]).sum()
    years = sorted(annual.index)
    hhi = db.hhi_series(importer, hs6).set_index("month")["hhi_12m"]
    hhi = hhi[(hhi.index >= f"{start}-01") & (hhi.index <= f"{end}-12")].dropna()
    # Growth uses whole years so a part-year at the end does not distort it.
    full_years = [y for y in years if (df.index.str[:4] == y).sum() == 12]
    summary = {
        "share_start": df["share"].iloc[:12].mean(),
        "share_end": df["share"].iloc[-12:].mean(),
        "value_end": df["value"].iloc[-12:].sum(),
        "yoy_latest": yoy_growth(df["value"].rolling(12).sum()).iloc[-1] if len(df) >= 24 else float("nan"),
        "cagr": (
            cagr(annual[full_years[0]], annual[full_years[-1]], len(full_years) - 1)
            if len(full_years) >= 2
            else float("nan")
        ),
        "cagr_years": f"{full_years[0]}–{full_years[-1]}" if len(full_years) >= 2 else "",
        "hhi_change": (hhi.iloc[-1] - hhi.iloc[0]) if len(hhi) >= 2 else float("nan"),
    }
    summary["share_change"] = summary["share_end"] - summary["share_start"]
    return df, summary


def labels(mode: str, a: str, b: str, f: dict, names: dict) -> tuple[tuple, tuple]:
    """(importer, hs6, supplier) for each side, depending on the mode."""
    if mode == "suppliers":
        return (f["importer"], f["hs6"], a), (f["importer"], f["hs6"], b)
    if mode == "products":
        return (f["importer"], a, f["supplier"]), (f["importer"], b, f["supplier"])
    return (a, f["hs6"], f["supplier"] or "CN"), (b, f["hs6"], f["supplier"] or "CN")


@bp.route("/compare")
def page():
    """Render a two-way comparison."""
    f = filters()
    mode = request.args.get("mode", "suppliers")
    if mode not in DEFAULTS:
        mode = "suppliers"
    a = request.args.get("a", "").upper().strip() or DEFAULTS[mode][0]
    b = request.args.get("b", "").upper().strip() or DEFAULTS[mode][1]
    start, end = request.args.get("start", "2016"), request.args.get("end", "2025")
    names = db.countries()
    spec_a, spec_b = labels(mode, a, b, f, names)

    def label(spec: tuple) -> str:
        imp, hs6, sup = spec
        who = names.get(sup, sup) if sup else "all suppliers"
        return {"suppliers": who, "products": f"HS {hs6[:4]}.{hs6[4:]}", "importers": names.get(imp, imp)}[mode]

    (df_a, s_a), (df_b, s_b) = side(*spec_a, start, end), side(*spec_b, start, end)
    la, lb = label(spec_a), label(spec_b)
    charts, rows, summary = [], [], []
    if s_a and s_b:
        share = pd.DataFrame({la: df_a["share"], lb: df_b["share"]}).rolling(12, min_periods=12).mean()
        index = pd.DataFrame({la: df_a["value"].rolling(12).sum(), lb: df_b["value"].rolling(12).sum()})
        index = 100 * index / index.dropna().iloc[0]
        charts = [
            line_chart("cmp_share", "Market share, 12-month average (%)", share.dropna(how="all"), "pct"),
            line_chart(
                "cmp_index", "Import value, 12-month total, indexed to 100 at start", index.dropna(how="all"), "index"
            ),
        ]
        for name, s in ((la, s_a), (lb, s_b)):
            rows.append({"side": name, **s})
        summary = [
            f"{la}: share went from {s_a['share_start']:.1f}% to {s_a['share_end']:.1f}% ({s_a['share_change']:+.1f} pts); "
            f"{lb}: from {s_b['share_start']:.1f}% to {s_b['share_end']:.1f}% ({s_b['share_change']:+.1f} pts).",
            f"Compound annual growth of import value over {s_a['cagr_years'] or 'the period'}: {la} {s_a['cagr']:+.1f}%, "
            f"{lb} {s_b['cagr']:+.1f}%.",
        ]
    else:
        summary = ["One side has no data for these choices; try another code or period."]
    table = {
        "title": "Side by side",
        "columns": [
            {"key": "side", "label": ""},
            {"key": "share_start", "label": "Share, first 12m", "format": "pct"},
            {"key": "share_end", "label": "Share, last 12m", "format": "pct"},
            {"key": "share_change", "label": "Share change", "format": "pts"},
            {"key": "value_end", "label": "Value, last 12m", "format": "usd_m"},
            {"key": "yoy_latest", "label": "Year-on-year growth", "format": "signed_pct"},
            {"key": "cagr", "label": "CAGR", "format": "signed_pct"},
            {"key": "hhi_change", "label": "HHI change", "format": "signed_hhi"},
        ],
        "rows": [{k: (None if isinstance(v, float) and v != v else v) for k, v in r.items()} for r in rows],
    }
    params = {
        "mode": mode,
        "a": a,
        "b": b,
        "importer": f["importer"],
        "hs6": f["hs6"],
        "supplier": f["supplier"],
        "start": start,
        "end": end,
    }
    meta = {"hs6": spec_a[1], "importer": spec_a[0], "supplier": spec_a[2], "event_id": ""}
    an = analysis("compare", f"Compare {mode}: {la} vs {lb}", params, meta, summary, charts, [table], [])
    return render_template(
        "compare.html", a=an, f=f, mode=mode, va=a, vb=b, start=start, end=end, importers=db.importers()
    )
