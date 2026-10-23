"""Market shares, growth, CAGR, HHI and before/after event windows.

What it does:
    Pure functions for the economics (each cites its section of the brief), plus a
    `run()` that applies them to the processed trade tables:
      * HHI per importer, product and month, with a 12-month rolling version.
      * For every tariff event and covered product: each supplier's value and
        quantity share in the 12 months before vs the 12 months after (minus a
        short lag). The detector and the DiD check both start from this table.

Inputs:
    processed/trade/<importer>/<hs2>.csv.gz, data/tariff_events.csv,
    data/tariff_event_products.csv, data/countries.csv, processed/products.csv.gz.

Outputs:
    processed/hhi/<importer>/<hs2>.csv.gz      importer, hs6, month, total_value, n_suppliers, hhi, hhi_12m
    processed/event_shares.csv.gz              event_id, hs6, supplier, tariffed, value/share/qshare before and after
    processed/event_products.csv.gz            event_id, hs6, totals, HHI before/after, hs_changed

How to run:
    python -m batch.metrics
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from batch.storage_io import store
from config.logging_config import setup_logging
from config.settings import settings

log = logging.getLogger("metrics")


# ---------------------------------------------------------------------------
# Formulas
# ---------------------------------------------------------------------------


def market_shares(
    df: pd.DataFrame, value_col: str = "value_usd", keys: tuple[str, ...] = ("importer", "hs6", "month")
) -> pd.Series:
    """Supplier share of an importer's purchases of a product in a month.

    share(j, k, t) = imports of k from j / total imports of k, in month t
    (Methodology 4.1, "Market share").

    Args:
        df: One row per supplier with a value column.
        value_col: Column to share out (value or quantity).
        keys: Columns that define one market.

    Returns:
        Shares between 0 and 1, aligned to df's index. NaN where the market total is 0.
    """
    total = df.groupby(list(keys))[value_col].transform("sum")
    return df[value_col] / total.replace(0, np.nan)


def hhi(shares: pd.Series | np.ndarray) -> float:
    """Herfindahl-Hirschman Index of supplier concentration.

    HHI = sum over suppliers of (100 x share)^2, from near 0 (many small suppliers)
    to 10,000 (one supplier). (Features, "Concentration score".)

    Args:
        shares: Supplier shares as fractions that sum to 1.

    Returns:
        HHI between 0 and 10,000.
    """
    s = np.asarray(shares, dtype=float)
    s = s[~np.isnan(s)]
    return float(np.sum((100 * s) ** 2))


def yoy_growth(series: pd.Series) -> pd.Series:
    """Year-on-year growth in percent for a monthly series (Feature 2, comparison).

    Args:
        series: Monthly values indexed by consecutive months.

    Returns:
        100 x (value / value 12 months earlier - 1); NaN for the first year.
    """
    return 100 * (series / series.shift(12).replace(0, np.nan) - 1)


def cagr(first: float, last: float, years: float) -> float:
    """Compound annual growth rate in percent (Feature 2, comparison).

    CAGR = (last / first)^(1 / years) - 1

    Args:
        first: Value at the start (must be positive).
        last: Value at the end.
        years: Length of the period in years.

    Returns:
        CAGR in percent, or NaN if it is undefined.
    """
    if first <= 0 or last < 0 or years <= 0:
        return float("nan")
    return 100 * ((last / first) ** (1 / years) - 1)


def shift_month(month: str, n: int) -> str:
    """Return the month n months after `month` (negative n goes back). Format YYYY-MM."""
    y, m = map(int, month.split("-"))
    idx = y * 12 + (m - 1) + n
    return f"{idx // 12}-{idx % 12 + 1:02d}"


def event_windows(effective_date: str, window: int, lag: int) -> tuple[list[str], list[str]]:
    """Months in the before and after windows of a tariff event (Methodology 4.3).

    Before: the `window` months ending the month before the effective month.
    After: `window` months starting `lag` months after the effective month, so
    goods already shipped when the tariff hit do not count.

    Args:
        effective_date: "YYYY-MM-DD" date the tariff took effect.
        window: Months in each window (12).
        lag: Months skipped after the effective month (2).

    Returns:
        (before_months, after_months) as YYYY-MM lists.
    """
    start = effective_date[:7]
    before = [shift_month(start, -i) for i in range(window, 0, -1)]
    after = [shift_month(start, lag + i) for i in range(window)]
    return before, after


def tariffed_set(event: pd.Series, all_suppliers: set[str], eu: set[str]) -> set[str]:
    """Return the ISO codes of suppliers an event put a tariff on.

    Why a set: Section 232 hit many countries with exemptions, so one event can have
    several tariffed suppliers (Data rules).

    Args:
        event: One row of tariff_events.csv.
        all_suppliers: Every supplier code in the data (used for "ALL").
        eu: EU member codes, used to expand "EU".

    Returns:
        Set of tariffed ISO alpha-2 codes ("ROW" is never tariffed).
    """

    def expand(cell: object) -> set[str]:
        codes: set[str] = set()
        for code in str(cell or "").split(";"):
            code = code.strip()
            if code == "EU":
                codes |= eu
            elif code == "ALL":
                codes |= all_suppliers
            elif code and code != "nan":
                codes.add(code)
        return codes

    return (expand(event["tariffed_suppliers"]) - expand(event["exempt_suppliers"])) - {"ROW"}


def window_shares(trade: pd.DataFrame, before: list[str], after: list[str]) -> pd.DataFrame:
    """Each supplier's pooled value and quantity share in the before and after windows.

    Shares are pooled over the 12 months (window value / window total), which is the
    value-weighted average of monthly shares and removes seasonality (Methodology 4.1).

    Args:
        trade: Tidy rows for one importer (hs6, supplier, month, value_usd, qty).
        before: Months in the before window.
        after: Months in the after window.

    Returns:
        One row per (hs6, supplier) with value_/share_/qshare_ before and after.
    """
    parts = []
    for label, months in (("before", before), ("after", after)):
        w = trade[trade["month"].isin(months)]
        g = w.groupby(["hs6", "supplier"], as_index=False).agg(value=("value_usd", "sum"), qty=("qty", "sum"))
        g["share"] = market_shares(g, "value", ("hs6",))
        g["qshare"] = market_shares(g, "qty", ("hs6",))
        parts.append(g.set_index(["hs6", "supplier"]).add_suffix(f"_{label}"))
    out = (
        parts[0]
        .join(parts[1], how="outer")
        .fillna({"value_before": 0, "value_after": 0, "share_before": 0, "share_after": 0})
    )
    # A quantity share is meaningful only if the product reports quantities in both windows.
    for label in ("before", "after"):
        qty_total = out.groupby(level="hs6")[f"qty_{label}"].transform("sum")
        out.loc[qty_total <= 0, f"qshare_{label}"] = np.nan
    return out.drop(columns=["qty_before", "qty_after"]).reset_index()


def hhi_table(trade: pd.DataFrame) -> pd.DataFrame:
    """HHI per importer, product and month, plus a 12-month rolling mean.

    Args:
        trade: Tidy rows for any number of products.

    Returns:
        importer, hs6, month, total_value, n_suppliers, hhi, hhi_12m
    """
    t = trade[trade["value_usd"] > 0].copy()
    t["share"] = market_shares(t)
    t["sq"] = (100 * t["share"]) ** 2
    out = t.groupby(["importer", "hs6", "month"], as_index=False).agg(
        total_value=("value_usd", "sum"), n_suppliers=("supplier", "nunique"), hhi=("sq", "sum")
    )
    out = out.sort_values(["importer", "hs6", "month"])
    out["hhi_12m"] = out.groupby(["importer", "hs6"])["hhi"].transform(lambda s: s.rolling(12, min_periods=6).mean())
    return out


def crosses_revision(before: list[str], after: list[str], revised_in: object) -> bool:
    """True if the product's code changed at an HS revision inside the event windows."""
    if not isinstance(revised_in, str) or not revised_in:
        return False
    return before[0] <= revised_in <= after[-1]


# ---------------------------------------------------------------------------
# Batch step
# ---------------------------------------------------------------------------


def load_trade(importer: str, first_month: str = "", last_month: str = "9999-12") -> pd.DataFrame:
    """Read every processed chapter file for one importer into one DataFrame.

    Args:
        importer: ISO alpha-2 of the importer.
        first_month: Keep months from this one (YYYY-MM); empty keeps all.
        last_month: Keep months up to this one.

    Returns:
        Tidy rows; filtering chapter by chapter keeps peak memory low.
    """
    frames = []
    for key in store.list(f"{settings.processed_prefix}trade/{importer}/"):
        df = store.read_df(key, dtype={"hs6": str, "supplier": str, "month": str})
        frames.append(df[(df["month"] >= first_month) & (df["month"] <= last_month)])
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def event_tables(
    trade: pd.DataFrame, ev: pd.Series, codes: set[str], tariffed: set[str], revised: pd.Series
) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """Before/after supplier shares and product summary for one event and one chapter.

    Args:
        trade: US tidy rows for one HS2 chapter.
        ev: One row of tariff_events.csv.
        codes: HS6 codes the event covers.
        tariffed: Supplier codes the event tariffed.
        revised: {hs6: revision month} from processed/products.

    Returns:
        (supplier rows, product summary rows), or None if the chapter has no covered products.
    """
    subset = trade[trade["hs6"].isin(codes)]
    if subset.empty:
        return None
    before, after = event_windows(ev["effective_date"], settings.window_months, settings.lag_months)
    ws = window_shares(subset, before, after)
    ws["tariffed"] = ws["supplier"].isin(tariffed)
    ws.insert(0, "event_id", ev["event_id"])

    summ = ws.groupby("hs6").agg(total_before=("value_before", "sum"), total_after=("value_after", "sum"))
    summ["hhi_before"] = ws.groupby("hs6")["share_before"].apply(hhi)
    summ["hhi_after"] = ws.groupby("hs6")["share_after"].apply(hhi)
    summ["hs_changed"] = [crosses_revision(before, after, revised.get(code)) for code in summ.index]
    summ = summ.reset_index()
    summ.insert(0, "event_id", ev["event_id"])
    summ["before_start"], summ["after_end"] = before[0], after[-1]
    return ws, summ


def run() -> None:
    """Compute the HHI tables and the event before/after tables, one chapter at a time.

    Why chapter by chapter: a decade of HS6-by-supplier data does not fit in a
    small batch instance's memory, but one chapter does.
    """
    events = pd.read_csv(settings.events_file, dtype=str)
    event_products = pd.read_csv(settings.event_products_file, dtype=str)
    countries = pd.read_csv(settings.country_file, dtype=str, keep_default_na=False)
    eu = set(countries.loc[countries["is_eu"] == "1", "iso2"])
    products = store.read_df(f"{settings.processed_prefix}products.csv.gz", dtype=str)
    revised = products.set_index("hs6")["revised_in"]
    # "ALL" in the events table means every country, so expand it against the country list.
    all_suppliers = set(countries["iso2"])
    codes = {e: set(g["hs6"]) for e, g in event_products.groupby("event_id")}
    tariffed = {ev["event_id"]: tariffed_set(ev, all_suppliers, eu) for _, ev in events.iterrows()}

    shares_out, summary_out = [], []
    for importer in ("US", settings.second_importer_iso2):
        for key in store.list(f"{settings.processed_prefix}trade/{importer}/"):
            trade = store.read_df(key, dtype={"hs6": str, "supplier": str, "month": str})
            store.write_df(key.replace("/trade/", "/hhi/"), hhi_table(trade))
            # Event windows use the US series: every event in the table is a US tariff.
            if importer != "US":
                continue
            for _, ev in events.iterrows():
                result = event_tables(trade, ev, codes.get(ev["event_id"], set()), tariffed[ev["event_id"]], revised)
                if result:
                    shares_out.append(result[0])
                    summary_out.append(result[1])

    shares = pd.concat(shares_out, ignore_index=True)
    summary = pd.concat(summary_out, ignore_index=True)
    for event_id, n in summary.groupby("event_id").size().items():
        log.info("%s: %d products", event_id, n)
    store.write_df(f"{settings.processed_prefix}event_shares.csv.gz", shares)
    store.write_df(f"{settings.processed_prefix}event_products.csv.gz", summary)


if __name__ == "__main__":
    setup_logging()
    run()
