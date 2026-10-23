"""Build data/tariff_event_products.csv from the official Federal Register notices.

What it does:
    Downloads the USTR Section 301 notices (PDF, from govinfo.gov via the Federal
    Register API), pulls every 8-digit HTSUS subheading out of the annex that lists
    the covered products, and writes one row per (event, HTS8 code). Section 232
    steel and aluminium are defined by HTS ranges in the proclamations, so those
    rows are generated from the ranges below instead of parsed.

Inputs:
    Internet access to federalregister.gov and govinfo.gov (one-off, run by a
    developer, never during the demo). Needs pypdf (requirements-dev.txt).

Outputs:
    data/tariff_event_products.csv with columns
    event_id, hts8, hs6, coverage, source_url

How to run:
    python scripts/build_tariff_lines.py
"""

from __future__ import annotations

import csv
import io
import logging
import re
import sys
from pathlib import Path

import requests
from pypdf import PdfReader

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
log = logging.getLogger("build_tariff_lines")

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_FILE = REPO_ROOT / "data" / "tariff_event_products.csv"
FR_API = "https://www.federalregister.gov/api/v1/documents/{doc}.json?fields[]=pdf_url&fields[]=html_url"

# Each Section 301 notice has a "formal" annex (legal text) and an "informal" annex
# that lists every covered HTS8 code with a description. We parse the informal one
# because it is a clean code list. start/end are the annex headings as pypdf prints them.
SECTION_301 = [
    {"event_id": "S301_L1", "doc": "2018-13248", "start": r"^ANNEX ?B\b", "end": r"^ANNEX ?C\b"},
    {"event_id": "S301_L2", "doc": "2018-17709", "start": r"^ANNEX ?B\b", "end": r"^ANNEX ?C\b"},
    {"event_id": "S301_L3", "doc": "2018-20610", "start": r"^ANNEX ?C\b", "end": None},
    {"event_id": "S301_L4A", "doc": "2019-17865", "start": r"^ANNEX ?B\b", "end": r"^ANNEX ?C\b"},
]

# Section 232 product scope, from Proclamation 9705 (steel) and 9704 (aluminium), cl. 1.
# Ranges are inclusive HS6 bounds; HTS8-level carve-outs are ignored at HS6 level.
SECTION_232 = {
    "S232_STEEL": {
        "source_url": "https://www.federalregister.gov/documents/2018/03/15/2018-05478",
        "ranges": [
            ("720610", "721650"),
            ("721699", "730110"),
            ("730210", "730210"),
            ("730240", "730290"),
            ("730410", "730690"),
        ],
    },
    "S232_ALUM": {
        "source_url": "https://www.federalregister.gov/documents/2018/03/15/2018-05477",
        "ranges": [
            ("760110", "760120"),
            ("760410", "760429"),
            ("760511", "760529"),
            ("760611", "760692"),
            ("760711", "760720"),
            ("760810", "760820"),
            ("760900", "760900"),
            ("761699", "761699"),
        ],
    },
}
# The June 2018 extension to the EU, Canada and Mexico covers the same products.
SECTION_232_ALIASES = {"S232_STEEL_EXT": "S232_STEEL", "S232_ALUM_EXT": "S232_ALUM"}

# Section 201 safeguard on large residential washers, Proclamation 9694, Annex I:
# finished washers (8450.11, 8450.20) and covered parts (8450.90).
SECTION_201_WASHERS = {
    "event_id": "S201_WASHERS",
    "hs6": ["845011", "845020", "845090"],
    "source_url": "https://www.federalregister.gov/documents/2018/01/25/2018-01604",
}

# Anti-dumping duties on large residential washers from China, preliminary determination
# (81 FR 48741): washers of HS 8450.11 and 8450.20 (the scope's HTSUS statistical lines).
AD_WASHERS_CN = {
    "event_id": "AD_WASHERS_CN",
    "hs6": ["845011", "845020"],
    "source_url": "https://www.federalregister.gov/documents/2016/07/26/2016-17680",
}

HTS8_RE = re.compile(r"\b(\d{4})\.(\d{2})\.(\d{2})\b")


def fetch_pdf_text(doc: str) -> tuple[str, str]:
    """Download one Federal Register document as PDF and return (text, html_url).

    Args:
        doc: Federal Register document number, e.g. "2018-13248".

    Returns:
        The extracted plain text of every page, and the human-readable notice URL.
    """
    meta = requests.get(FR_API.format(doc=doc), timeout=60).json()
    pdf = requests.get(meta["pdf_url"], timeout=300)
    pdf.raise_for_status()
    reader = PdfReader(io.BytesIO(pdf.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    log.info("Fetched %s: %d pages", doc, len(reader.pages))
    return text, meta["html_url"]


def annex_codes(text: str, start: str, end: str | None) -> list[str]:
    """Return the HTS8 codes that appear between two annex headings.

    Args:
        text: Full text of a notice.
        start: Regex for the heading where the product list begins.
        end: Regex for the next heading, or None to read to the end.

    Returns:
        HTS8 codes without dots, in first-seen order, no duplicates.
    """
    lines = text.splitlines()
    start_i = next(i for i, line in enumerate(lines) if re.search(start, line.strip(), re.I))
    end_i = len(lines)
    if end:
        end_i = next((i for i in range(start_i + 1, len(lines)) if re.search(end, lines[i].strip(), re.I)), len(lines))
    seen: dict[str, None] = {}
    for line in lines[start_i:end_i]:
        for a, b, c in HTS8_RE.findall(line):
            seen[a + b + c] = None
    return list(seen)


def hs6_in_ranges(ranges: list[tuple[str, str]], universe: set[str]) -> list[str]:
    """Return every HS6 code from `universe` that falls inside any inclusive range.

    Args:
        ranges: (low, high) HS6 bounds as strings.
        universe: All HS6 codes seen in the Section 301 lists, used as the code list.

    Returns:
        Sorted HS6 codes covered by the ranges.
    """
    return sorted(code for code in universe if any(lo <= code <= hi for lo, hi in ranges))


def main() -> None:
    """Build the product file for every tariff event and write it to data/."""
    rows: list[dict[str, str]] = []
    for spec in SECTION_301:
        text, url = fetch_pdf_text(spec["doc"])
        codes = annex_codes(text, spec["start"], spec["end"])
        log.info("%s: %d HTS8 codes", spec["event_id"], len(codes))
        rows += [
            {"event_id": spec["event_id"], "hts8": c, "hs6": c[:6], "coverage": "listed", "source_url": url}
            for c in codes
        ]

    # Section 232 ranges are expanded against a full HS6 code list from chapters 72-76.
    # Using the HTS itself keeps the list exact: the USITC HTS API returns every line.
    hts = requests.get(
        "https://hts.usitc.gov/reststop/exportList?from=7201&to=7699&format=JSON&styles=false", timeout=120
    ).json()
    universe = {re.sub(r"\D", "", r["htsno"])[:6] for r in hts if len(re.sub(r"\D", "", r["htsno"])) >= 6}
    for event_id, spec in SECTION_232.items():
        codes = hs6_in_ranges(spec["ranges"], universe)
        log.info("%s: %d HS6 codes", event_id, len(codes))
        rows += [
            {"event_id": event_id, "hts8": "", "hs6": c, "coverage": "range", "source_url": spec["source_url"]}
            for c in codes
        ]
    for alias, base in SECTION_232_ALIASES.items():
        rows += [{**r, "event_id": alias} for r in rows if r["event_id"] == base]
    rows += [
        {
            "event_id": SECTION_201_WASHERS["event_id"],
            "hts8": "",
            "hs6": c,
            "coverage": "listed",
            "source_url": SECTION_201_WASHERS["source_url"],
        }
        for c in SECTION_201_WASHERS["hs6"]
    ]
    rows += [
        {
            "event_id": AD_WASHERS_CN["event_id"],
            "hts8": "",
            "hs6": c,
            "coverage": "listed",
            "source_url": AD_WASHERS_CN["source_url"],
        }
        for c in AD_WASHERS_CN["hs6"]
    ]

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUT_FILE.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["event_id", "hts8", "hs6", "coverage", "source_url"])
        writer.writeheader()
        writer.writerows(rows)
    log.info("Wrote %d rows to %s", len(rows), OUT_FILE)


if __name__ == "__main__":
    main()
