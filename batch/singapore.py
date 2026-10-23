"""Singapore lens: products where Singapore's re-exports to the US grew after the tariffs.

What it does:
    For every product on a Section 301 list, compares the 12 months before vs after
    the first list that covered it (Methodology 4.6):
      * Singapore's total exports of the product to the US (Comtrade),
      * US imports of Singapore-origin goods (Census),
      * estimated re-exports = exports minus Singapore-origin imports.
    A product is flagged when estimated re-exports grew by at least
    SG_MIN_GROWTH_PCT and are above SG_MIN_VALUE_USD afterwards. China's share
    change for the same product comes from the event table.

    Why an estimate: no free source splits Singapore's re-exports by HS6 product.
    SingStat publishes the official split only as totals, which the page charts next
    to the sum of our estimates as a check.

    Why this is "hub growth", not transshipment: US data records country of origin,
    so goods passing through Singapore are still counted under where they were
    made. Growth in re-exports shows Singapore's hub role growing, not evasion.
    The page says so.

Inputs:
    processed/singapore.csv.gz, processed/event_shares.csv.gz,
    data/tariff_events.csv, data/tariff_event_products.csv.

Outputs:
    processed/singapore_lens.csv.gz, one row per product.

How to run:
    python -m batch.singapore
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from batch.metrics import event_windows
from batch.storage_io import store
from config.logging_config import setup_logging
from config.settings import settings

log = logging.getLogger("singapore")


def first_list_per_product(events: pd.DataFrame, event_products: pd.DataFrame) -> pd.DataFrame:
    """Return the earliest Section 301 list covering each HS6 code (event_id, effective_date)."""
    s301 = events[events["measure"] == "Section 301"][["event_id", "effective_date"]]
    ep = event_products[["event_id", "hs6"]].drop_duplicates().merge(s301, on="event_id")
    return ep.sort_values("effective_date").drop_duplicates("hs6")


def lens_table(sg: pd.DataFrame, firsts: pd.DataFrame, china: pd.DataFrame) -> pd.DataFrame:
    """Before/after exports, Singapore-origin imports and estimated re-exports per product.

    Args:
        sg: Monthly HS6 Singapore table (hs6, month, sg_exports_usd,
            us_imports_sg_origin_usd, est_reexports_usd).
        firsts: Earliest Section 301 list per product (hs6, event_id, effective_date).
        china: China's before/after share per (event_id, hs6), as fractions.

    Returns:
        One row per product with before/after values, growth, and the flag.
    """
    cols = {"sg_exports_usd": "exports", "us_imports_sg_origin_usd": "origin", "est_reexports_usd": "est_rx"}
    by_product = {h: g.set_index("month") for h, g in sg.groupby("hs6")}
    rows = []
    for r in firsts.itertuples():
        series = by_product.get(r.hs6)
        if series is None:
            continue
        before, after = event_windows(r.effective_date, settings.window_months, settings.lag_months)
        row = {"hs6": r.hs6, "event_id": r.event_id}
        for col, short in cols.items():
            row[f"{short}_before"] = series.loc[series.index.isin(before), col].sum()
            row[f"{short}_after"] = series.loc[series.index.isin(after), col].sum()
        rows.append(row)
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["est_rx_growth_pct"] = 100 * (out["est_rx_after"] / out["est_rx_before"].replace(0, np.nan) - 1)
    out["est_rx_share_after_pct"] = 100 * out["est_rx_after"] / out["exports_after"].replace(0, np.nan)
    out = out.merge(china, on=["event_id", "hs6"], how="left")
    # New re-export lines (zero before, real value after) count as growth too.
    grew = (out["est_rx_growth_pct"] >= settings.sg_min_growth_pct) | (
        out["est_rx_before"].eq(0) & out["est_rx_after"].gt(0)
    )
    out["flagged"] = grew & (out["est_rx_after"] >= settings.sg_min_value_usd)
    return out.sort_values("est_rx_after", ascending=False)


def run() -> pd.DataFrame:
    """Build and save the Singapore lens table."""
    sg = store.read_df(f"{settings.processed_prefix}singapore.csv.gz", dtype={"hs6": str, "month": str})
    events = pd.read_csv(settings.events_file, dtype=str)
    event_products = pd.read_csv(settings.event_products_file, dtype=str)
    shares = store.read_df(f"{settings.processed_prefix}event_shares.csv.gz", dtype={"hs6": str, "supplier": str})
    china = shares[shares["supplier"] == "CN"][["event_id", "hs6", "share_before", "share_after"]].rename(
        columns={"share_before": "cn_share_before", "share_after": "cn_share_after"}
    )
    out = lens_table(sg, first_list_per_product(events, event_products), china)
    store.write_df(f"{settings.processed_prefix}singapore_lens.csv.gz", out)
    log.info("Singapore lens: %d products, %d flagged", len(out), int(out["flagged"].sum()) if len(out) else 0)
    return out


if __name__ == "__main__":
    setup_logging()
    run()
