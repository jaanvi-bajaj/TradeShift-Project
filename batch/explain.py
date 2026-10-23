"""Plain-language summaries for every flagged product, each with source links.

What it does:
    Fills a sentence from computed figures for each detector flag (Methodology 4.5):
      "Since the Jul 2018 tariff (Section 301 List 1), China's share of US imports of
       <product> fell from 62.0% to 41.0%, while Vietnam's rose from 8.0% to 24.0%.
       Total US imports of the product rose 5.0%, so this looks like diversion."
    The total-import change is stated so readers can tell diversion (others gain)
    from trade destruction (the market shrinks). Every flag gets two links: the
    legal source of the tariff, and the app's source page showing the exact data
    query and numbers behind the sentence (Feature 1).

Inputs:
    processed/signals.csv.gz, processed/products.csv.gz, data/countries.csv,
    data/tariff_events.csv.

Outputs:
    processed/signals_explained.csv.gz (signals plus explanation, source_url, data_url).

How to run:
    python -m batch.explain
"""

from __future__ import annotations

import logging

import pandas as pd

from app.formatting import month_label, pct, signed_pct
from batch.storage_io import store
from config.logging_config import setup_logging
from config.settings import settings

log = logging.getLogger("explain")


def country_names() -> dict[str, str]:
    """Return {iso2: short display name}, e.g. "KR" -> "South Korea"."""
    c = pd.read_csv(settings.country_file, dtype=str, keep_default_na=False)
    # Census names carry long forms in brackets: "South Korea (Republic of Korea)".
    names = {r.iso2: r.name.split(" (")[0] for r in c.itertuples()}
    names["ROW"] = "the rest of the world"
    return names


def short_description(text: object, limit: int = 70) -> str:
    """Trim a Census product description to a readable length, in lower case.

    Census short descriptions are upper case ("WASHING MACHINES, HOUSEHOLD..."),
    which reads as shouting inside a sentence.
    """
    text = str(text or "this product").strip().rstrip(",;").lower()
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def explain_row(row: pd.Series, names: dict[str, str], descriptions: dict[str, str], events: pd.DataFrame) -> str:
    """Build the one-sentence summary for one flag.

    Args:
        row: One signal (see batch/detector.py SIGNAL_COLUMNS).
        names: ISO code to country name.
        descriptions: HS6 code to product description.
        events: tariff_events.csv indexed by event_id.

    Returns:
        The summary sentence.
    """
    ev = events.loc[row["event_id"]]
    loser, gainer = names.get(row["loser"], row["loser"]), names.get(row["gainer"], row["gainer"])
    product = short_description(descriptions.get(row["hs6"]))
    change = row["total_change_pct"]
    direction = "rose" if change >= 0 else "fell"
    if row["pattern"] == "diversion":
        verdict = "so this looks like diversion to other suppliers"
    else:
        verdict = "so part of the lost share left the market altogether (trade destruction), not only diversion"
    text = (
        f"Since the {month_label(ev['effective_date'])} tariff ({ev['name']}), {loser}'s share of US imports of "
        f"{product} (HS {row['hs6'][:4]}.{row['hs6'][4:]}) fell from {pct(row['loser_share_before'])} to "
        f"{pct(row['loser_share_after'])}, while {gainer}'s rose from {pct(row['gainer_share_before'])} to "
        f"{pct(row['gainer_share_after'])}. Total US imports of the product {direction} "
        f"{signed_pct(change).lstrip('+-')}, {verdict}."
    )
    if row["confidence"] == "higher":
        text += " Quantities moved the same way, so this is not just a price effect."
    if bool(row.get("hs_changed")):
        text += " Caution: this HS code changed in a revision inside the comparison window."
    return text


def run() -> pd.DataFrame:
    """Add explanations and source links to every signal and save the result."""
    signals = store.read_df(f"{settings.processed_prefix}signals.csv.gz", dtype={"hs6": str})
    products = store.read_df(f"{settings.processed_prefix}products.csv.gz", dtype={"hs6": str})
    events = pd.read_csv(settings.events_file, dtype=str).set_index("event_id")
    names = country_names()
    descriptions = dict(zip(products["hs6"], products["description"]))
    signals["explanation"] = [explain_row(r, names, descriptions, events) for _, r in signals.iterrows()]
    signals["source_url"] = signals["event_id"].map(events["source_url"])
    # The app's own page that shows the query and numbers; it never calls an external API.
    signals["data_url"] = "/source/" + signals["event_id"] + "/" + signals["hs6"]
    store.write_df(f"{settings.processed_prefix}signals_explained.csv.gz", signals)
    log.info("Explained %d signals", len(signals))
    return signals


if __name__ == "__main__":
    setup_logging()
    run()
