"""Number display rules for the whole app (Feature 1).

What it does:
    One place that decides how numbers look, so no page ever shows a raw value
    like 4.07e+09: values in US$ millions, shares in %, point changes in "pts",
    HHI as a whole number from 0 to 10,000, months as "Jul 2018".

Inputs:
    Numbers (floats, ints, None/NaN) and YYYY-MM strings.

Outputs:
    Display strings.

How to run:
    Not run directly. Used by views, templates (as Jinja filters) and batch/explain.py.
"""

from __future__ import annotations

import math
from datetime import date

DASH = "–"  # shown for missing values instead of "nan"


def _missing(x: object) -> bool:
    """True for None, NaN and empty strings."""
    return x is None or x == "" or (isinstance(x, float) and math.isnan(x))


def usd_millions(x: float | None, decimals: int = 1) -> str:
    """Format a US dollar value in millions, e.g. 4_070_000_000 -> "US$4,070.0m".

    Args:
        x: Value in US dollars.
        decimals: Decimal places to keep.

    Returns:
        Display string, or a dash if missing.
    """
    if _missing(x):
        return DASH
    return f"US${float(x) / 1e6:,.{decimals}f}m"


def pct(x: float | None, decimals: int = 1, fraction: bool = False) -> str:
    """Format a percentage, e.g. 41.23 -> "41.2%".

    Args:
        x: The value, in percent (or as a fraction if `fraction` is True).
        decimals: Decimal places to keep.
        fraction: Set when x is 0..1 rather than 0..100.

    Returns:
        Display string, or a dash if missing.
    """
    if _missing(x):
        return DASH
    value = float(x) * (100 if fraction else 1)
    return f"{value:,.{decimals}f}%"


def signed_pct(x: float | None, decimals: int = 1) -> str:
    """Format a growth rate with its sign, e.g. -12.3 -> "-12.3%", 4 -> "+4.0%"."""
    if _missing(x):
        return DASH
    return f"{float(x):+,.{decimals}f}%"


def points(x: float | None, decimals: int = 1) -> str:
    """Format a change in percentage points with its sign, e.g. -21 -> "-21.0 pts"."""
    if _missing(x):
        return DASH
    return f"{float(x):+,.{decimals}f} pts"


def hhi(x: float | None) -> str:
    """Format an HHI as a whole number from 0 to 10,000, e.g. 3821.7 -> "3,822"."""
    if _missing(x):
        return DASH
    return f"{round(float(x)):,}"


def signed_hhi(x: float | None) -> str:
    """Format an HHI change with its sign, e.g. -512.4 -> "-512"."""
    if _missing(x):
        return DASH
    return f"{round(float(x)):+,}"


def month_label(month: str | None) -> str:
    """Turn "2018-07" (or "2018-07-06") into "Jul 2018"."""
    if _missing(month):
        return DASH
    y, m = int(str(month)[:4]), int(str(month)[5:7])
    return date(y, m, 1).strftime("%b %Y")


def hs_label(code: str | None) -> str:
    """Show an HS code with dots, e.g. "845020" -> "8450.20", "8450" -> "8450"."""
    if _missing(code):
        return DASH
    code = str(code)
    return f"{code[:4]}.{code[4:]}" if len(code) > 4 else code


def product_label(hs6: str, description: object, limit: int = 45) -> str:
    """Show a product as "8450.20 washing machines with dry linen…", cut at a word boundary.

    Args:
        hs6: Six-digit HS code.
        description: Census short description (upper case), or None.
        limit: Longest description to show, in characters.

    Returns:
        Display label.
    """
    text = "" if _missing(description) else str(description).strip().lower()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(",;/(") + "…"
    return f"{hs_label(hs6)} {text}".strip()


def format_value(x: object, fmt: str) -> str:
    """Format x with the named rule (a key of FILTERS); used by tables in templates."""
    return FILTERS[fmt](x) if fmt in FILTERS else (DASH if _missing(x) else str(x))


def index_value(x: float | None) -> str:
    """Format an index number (start = 100), e.g. 123.456 -> "123.5"."""
    if _missing(x):
        return DASH
    return f"{float(x):,.1f}"


FILTERS = {
    "usd_m": usd_millions,
    "pct": pct,
    "signed_pct": signed_pct,
    "pts": points,
    "hhi": hhi,
    "signed_hhi": signed_hhi,
    "month": month_label,
    "hs": hs_label,
    "index": index_value,
}
FILTERS["format_value"] = format_value
FILTERS["product"] = product_label
