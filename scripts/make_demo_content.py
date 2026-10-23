"""Create the demo analyses and notes that every new stack shows on its History page.

What it does:
    Opens a few TradeShift pages through the app itself (Flask's test client, no
    server needed), saves each as an analysis with a short note, then exports
    everything with the History page's Export function into
    processed/demo/tradeshift-export.zip. The next snapshot carries that file, and
    batch/load_demo.py imports it into new stacks whose History is still empty.

Inputs:
    A database loaded with the real data (DB_* settings) and local storage.

Outputs:
    processed/demo/tradeshift-export.zip in storage.

How to run:
    python scripts/make_demo_content.py      (after the pipeline has loaded the database)
"""

from __future__ import annotations

import html
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.app import create_app  # noqa: E402
from batch.load_demo import DEMO_KEY  # noqa: E402
from batch.storage_io import store  # noqa: E402
from config.logging_config import setup_logging  # noqa: E402

log = logging.getLogger("make_demo_content")

# (page, title, note). Notes are written as a group member would, about what the page shows.
DEMOS = [
    (
        "/explorer?importer=US&hs6=845020",
        "Washers: China to Thailand and Vietnam, 2016-17",
        "China's share collapses right after the July 2016 anti-dumping duties; Thailand and Vietnam take over. "
        "Compare with the 2018 safeguard, where total imports fall instead (trade destruction).",
    ),
    (
        "/detector?event_id=S301_L3",
        "Section 301 List 3: flagged products",
        "Biggest list by far. Check the DiD box: the tariffed share fell several points more than in untariffed "
        "products of the same headings.",
    ),
    (
        "/detector?event_id=S201_WASHERS",
        "Section 201 washers: trade destruction, not diversion",
        "Every big supplier was tariffed, so nobody untariffed could gain; total imports of HS 8450.20 fell by "
        "about a third. Use this in the presentation to explain the difference.",
    ),
    (
        "/compare?mode=suppliers&a=CN&b=VN&importer=US&hs6=940360&start=2016&end=2024",
        "Wooden furniture: China vs Vietnam",
        "Normalised comparison: Vietnam's share rises as China's falls after List 3.",
    ),
    (
        "/singapore",
        "Singapore lens: re-exports after the tariffs",
        "Remember to say: this shows Singapore's hub role growing, not proof of transshipment.",
    ),
]


def main() -> None:
    """Save the demo analyses and notes, then export them for the snapshot."""
    setup_logging()
    client = create_app().test_client()
    for url, title, note in DEMOS:
        page = client.get(url)
        if page.status_code != 200:
            raise SystemExit(f"{url} answered {page.status_code}")
        text = page.data.decode()
        payload = html.unescape(text.split('name="analysis" value="', 1)[1].split('"', 1)[0])
        saved = client.post("/history/save", data={"analysis": payload, "title": title})
        analysis_id = saved.headers["Location"].split("/history/")[1].split("?")[0]
        client.post(
            "/notes", data={"target_type": "analysis", "target_id": analysis_id, "body": note, "next": "/history"}
        )
        log.info("Saved demo analysis %s: %s", analysis_id, title)
    export = client.get("/history/export")
    store.write_bytes(DEMO_KEY, export.data)
    log.info("Wrote %s (%d bytes)", DEMO_KEY, len(export.data))


if __name__ == "__main__":
    main()
