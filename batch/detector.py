"""Diversion detector: flag products where a tariffed supplier loses share and another gains.

What it does:
    For each tariff event and covered product, a flag is raised when (Methodology 4.3):
      * a tariffed supplier's share falls by at least MIN_DROP_PP points,
      * an untariffed supplier's share rises by at least MIN_GAIN_PP points, and
      * the product's annual import value is above MIN_ANNUAL_VALUE_USD.
    Confidence is "higher" when quantity shares move the same way as value shares,
    because value alone can move with prices. Each flag records the value
    redirected, which ranks the top movers. `detect()` is also called by the web
    app when a user moves the threshold sliders.

Inputs:
    processed/event_shares.csv.gz, processed/event_products.csv.gz.

Outputs:
    processed/signals.csv.gz, one row per (event, product, losing supplier).

How to run:
    python -m batch.detector
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from batch.storage_io import store
from config.logging_config import setup_logging
from config.settings import settings

log = logging.getLogger("detector")

# A total-import fall bigger than this means part of the "lost share" left the
# market instead of moving to another supplier (Methodology 4.5).
DESTRUCTION_PCT = -25.0


@dataclass(frozen=True)
class Thresholds:
    """The three detector thresholds; defaults come from config/settings.py."""

    min_drop_pp: float = settings.min_drop_pp
    min_gain_pp: float = settings.min_gain_pp
    min_annual_value_usd: float = settings.min_annual_value_usd


def confidence(loser_qdrop: float, gainer_qgain: float) -> str:
    """Label a flag by whether quantity shares agree with value shares.

    Args:
        loser_qdrop: Fall in the losing supplier's quantity share, in points.
        gainer_qgain: Rise in the gaining supplier's quantity share, in points.

    Returns:
        "higher" if both quantity moves agree, "lower" if either disagrees,
        "value only" if the product has no comparable quantities.
    """
    if np.isnan(loser_qdrop) or np.isnan(gainer_qgain):
        return "value only"
    return "higher" if loser_qdrop > 0 and gainer_qgain > 0 else "lower"


def detect(shares: pd.DataFrame, products: pd.DataFrame, t: Thresholds | None = None) -> pd.DataFrame:
    """Apply the detector rules to before/after supplier shares.

    Args:
        shares: event_shares rows (event_id, hs6, supplier, tariffed, share_before,
            share_after, qshare_before, qshare_after, ...). Shares are fractions.
        products: event_products rows (event_id, hs6, total_before, total_after, ...).
        t: Thresholds to apply; defaults to the values in config/settings.py.

    Returns:
        One row per flag, sorted by value redirected (largest first). Shares in the
        output are in percent.
    """
    t = t or Thresholds()
    s = shares.copy()
    s["change_pp"] = 100 * (s["share_after"] - s["share_before"])
    s["qchange_pp"] = 100 * (s["qshare_after"] - s["qshare_before"])

    losers = s[s["tariffed"].astype(bool) & (s["change_pp"] <= -t.min_drop_pp)]
    # Diversion means trade moves to suppliers the tariff did not hit; "ROW" is a
    # bundle of small countries, so it can never be the named gainer.
    gainers = s[~s["tariffed"].astype(bool) & (s["supplier"] != "ROW") & (s["change_pp"] >= t.min_gain_pp)]
    best_gainer = gainers.sort_values("change_pp", ascending=False).drop_duplicates(["event_id", "hs6"])

    flags = losers.merge(best_gainer, on=["event_id", "hs6"], suffixes=("_loser", "_gainer"))
    flags = flags.merge(products, on=["event_id", "hs6"], how="left")
    # Annual value: both windows are 12 months, so the before total is an annual figure.
    flags = flags[flags["total_before"] >= t.min_annual_value_usd]
    if flags.empty:
        return pd.DataFrame(columns=SIGNAL_COLUMNS)

    avg_annual = (flags["total_before"] + flags["total_after"]) / 2
    redirected_pp = np.minimum(-flags["change_pp_loser"], flags["change_pp_gainer"])
    out = pd.DataFrame(
        {
            "event_id": flags["event_id"],
            "hs6": flags["hs6"],
            "loser": flags["supplier_loser"],
            "gainer": flags["supplier_gainer"],
            "loser_share_before": 100 * flags["share_before_loser"],
            "loser_share_after": 100 * flags["share_after_loser"],
            "gainer_share_before": 100 * flags["share_before_gainer"],
            "gainer_share_after": 100 * flags["share_after_gainer"],
            "drop_pp": -flags["change_pp_loser"],
            "gain_pp": flags["change_pp_gainer"],
            # Value redirected = share moved between the pair x average annual imports (4.3).
            "value_redirected_usd": redirected_pp / 100 * avg_annual,
            "total_before_usd": flags["total_before"],
            "total_after_usd": flags["total_after"],
            "total_change_pct": 100 * (flags["total_after"] / flags["total_before"] - 1),
            "confidence": [confidence(-a, b) for a, b in zip(flags["qchange_pp_loser"], flags["qchange_pp_gainer"])],
            "hhi_before": flags.get("hhi_before"),
            "hhi_after": flags.get("hhi_after"),
            "hs_changed": flags.get("hs_changed", False),
        }
    )
    out["pattern"] = np.where(out["total_change_pct"] <= DESTRUCTION_PCT, "diversion + trade destruction", "diversion")
    return out.sort_values("value_redirected_usd", ascending=False).reset_index(drop=True)


SIGNAL_COLUMNS = [
    "event_id",
    "hs6",
    "loser",
    "gainer",
    "loser_share_before",
    "loser_share_after",
    "gainer_share_before",
    "gainer_share_after",
    "drop_pp",
    "gain_pp",
    "value_redirected_usd",
    "total_before_usd",
    "total_after_usd",
    "total_change_pct",
    "confidence",
    "hhi_before",
    "hhi_after",
    "hs_changed",
    "pattern",
]


def run() -> pd.DataFrame:
    """Run the detector with the default thresholds and save the flags."""
    shares = store.read_df(f"{settings.processed_prefix}event_shares.csv.gz", dtype={"hs6": str, "supplier": str})
    products = store.read_df(f"{settings.processed_prefix}event_products.csv.gz", dtype={"hs6": str})
    signals = detect(shares, products)
    store.write_df(f"{settings.processed_prefix}signals.csv.gz", signals)
    for event_id, n in signals.groupby("event_id").size().items():
        log.info("%s: %d flags", event_id, n)
    return signals


if __name__ == "__main__":
    setup_logging()
    run()
