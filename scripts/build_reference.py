"""Build data/countries.csv: one row per country with its Census and Comtrade codes.

What it does:
    US Census uses its own 4-digit "Schedule C" country codes, UN Comtrade uses
    UN M49 numeric codes, and our tariff events use ISO alpha-2. This script joins
    the two official code lists on ISO alpha-2 so every dataset can be matched.

Inputs:
    Internet access to census.gov and comtradeapi.un.org (one-off developer step).

Outputs:
    data/countries.csv with columns iso2, name, census_code, comtrade_code, is_eu

How to run:
    python scripts/build_reference.py
"""

from __future__ import annotations

import csv
import logging
import sys
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
log = logging.getLogger("build_reference")

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_FILE = REPO_ROOT / "data" / "countries.csv"
CENSUS_URL = "https://www.census.gov/foreign-trade/schedules/c/country.txt"
COMTRADE_URL = "https://comtradeapi.un.org/files/v1/app/reference/partnerAreas.json"

# EU-28 as it stood in 2018 (the UK was still a member), which is the membership
# that matters for the June 2018 Section 232 extension to the EU.
EU_2018 = {
    "AT",
    "BE",
    "BG",
    "HR",
    "CY",
    "CZ",
    "DK",
    "EE",
    "FI",
    "FR",
    "DE",
    "GR",
    "HU",
    "IE",
    "IT",
    "LV",
    "LT",
    "LU",
    "MT",
    "NL",
    "PL",
    "PT",
    "RO",
    "SK",
    "SI",
    "ES",
    "SE",
    "GB",
}


# Shorter display names where the official one is long.
SHORT_NAMES = {"US": "United States"}


def census_codes() -> dict[str, tuple[str, str]]:
    """Return {iso2: (census_code, name)} parsed from the Schedule C text file."""
    text = requests.get(CENSUS_URL, timeout=60).text.replace("\r", "\n")
    out: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 3 and parts[0].isdigit() and len(parts[2]) == 2:
            out[parts[2]] = (parts[0], parts[1])
    log.info("Census: %d countries", len(out))
    return out


def comtrade_codes() -> dict[str, str]:
    """Return {iso2: comtrade_code} for current (not expired) Comtrade partner areas."""
    rows = requests.get(COMTRADE_URL, timeout=60).json()["results"]
    out: dict[str, str] = {}
    for r in rows:
        iso2 = r.get("PartnerCodeIsoAlpha2")
        if iso2 and not r.get("isGroup") and not r.get("entryExpiredDate"):
            # 842 ("USA incl. Puerto Rico") is the code Comtrade reporters use for the US.
            if iso2 == "US" and r["PartnerCode"] != 842:
                continue
            out[iso2] = str(r["PartnerCode"])
    # Reporters record Taiwan as 490 "Other Asia, nes", not 158, so match on 490.
    out["TW"] = "490"
    log.info("Comtrade: %d partner areas", len(out))
    return out


def main() -> None:
    """Join the two code lists and write data/countries.csv."""
    census = census_codes()
    comtrade = comtrade_codes()
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUT_FILE.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["iso2", "name", "census_code", "comtrade_code", "is_eu"])
        for iso2 in sorted(set(census) | set(comtrade)):
            code, name = census.get(iso2, ("", ""))
            name = SHORT_NAMES.get(iso2, name or iso2)
            writer.writerow([iso2, name, code, comtrade.get(iso2, ""), int(iso2 in EU_2018)])
    log.info("Wrote %s", OUT_FILE)


if __name__ == "__main__":
    main()
