"""Synthetic raw files in the exact shape of the Census and Comtrade API responses.

What it does: writes a small, made-up dataset (a few products, 2016-2020) into the
test storage folder so the whole pipeline and app can be exercised without API keys.
The numbers are invented: China's share of tariffed products falls after each
event and Vietnam's rises, so the detector has something to find.
Inputs: data/tariff_event_products.csv (to pick real covered HS6 codes).
Outputs: raw/census/*.json.gz, raw/comtrade/... in the test storage folder.
How to run: used by tests/test_pipeline_smoke.py; not real data.
"""

from __future__ import annotations

import pandas as pd

from batch.download_census import month_range
from batch.storage_io import store
from config.settings import settings

CENSUS_HEADER = [
    "CTY_CODE",
    "CTY_NAME",
    "I_COMMODITY",
    "I_COMMODITY_SDESC",
    "GEN_VAL_MO",
    "GEN_QY1_MO",
    "UNIT_QY1",
    "COMM_LVL",
    "time",
]
SUPPLIERS = {
    "5700": "CHINA",
    "5520": "VIETNAM",
    "5800": "KOREA, SOUTH",
    "2010": "MEXICO",
    "5490": "THAILAND",
    "1220": "CANADA",
}


def pick_products() -> dict[str, str]:
    """One covered HS6 code per event, plus an uncovered control in the same HS4. Returns {hs6: effective_month}."""
    ep = pd.read_csv(settings.event_products_file, dtype=str)
    ev = pd.read_csv(settings.events_file, dtype=str).set_index("event_id")
    chosen = {}
    for event_id in ["S201_WASHERS", "S301_L1", "S301_L3", "S232_STEEL"]:
        code = sorted(ep.loc[ep["event_id"] == event_id, "hs6"])[0]
        chosen[code] = ev.loc[event_id, "effective_date"][:7]
    return chosen


def write_fake_raw(months: list[str] | None = None) -> dict[str, str]:
    """Write synthetic raw files for 2016-01 to 2020-12. Returns the chosen products."""
    months = months or month_range("2016-01", "2020-12")
    products = pick_products()
    for month in months:
        table = [CENSUS_HEADER]
        for hs6, eff in products.items():
            after = month >= eff
            shares = {
                "5700": 0.55 - (0.25 if after else 0),
                "5520": 0.05 + (0.25 if after else 0),
                "5800": 0.15,
                "2010": 0.15,
                "5490": 0.06,
                "1220": 0.04,
            }
            total = 50e6 * (1.1 if after else 1.0)
            for code, name in SUPPLIERS.items():
                value = total * shares[code]
                # Like the real API: Census gives no quantity at HS6.
                table.append([code, name, hs6, f"PRODUCT {hs6}", str(round(value)), "0", "-", "HS6", month])
            table.append(
                ["-", "TOTAL FOR ALL COUNTRIES", hs6, f"PRODUCT {hs6}", str(round(total)), "", "NO", "HS6", month]
            )
            table.append(["0003", "EUROPEAN UNION", hs6, f"PRODUCT {hs6}", "12345", "", "NO", "HS6", month])
        store.write_json_gz(f"{settings.raw_prefix}census/{month}.json.gz", table)

        jp = [
            {
                "period": month.replace("-", ""),
                "partnerCode": p,
                "cmdCode": hs6,
                "primaryValue": v,
                "netWgt": v / 3,
                "qtyUnitCode": 5,
            }
            for hs6 in products
            for p, v in ((156, 3e6), (704, 1e6), (0, 4e6))
        ]
        store.write_json_gz(f"{settings.raw_prefix}comtrade/imports_392/{month}.json.gz", jp)
        if "2017-01" <= month <= "2020-12":
            # US net weights reported to Comtrade: China's halve and Vietnam's double after each event.
            us = []
            for hs6, eff in products.items():
                after = month >= eff
                for partner, kg in ((156, 1e5 * (0.5 if after else 1.0)), (704, 1e4 * (2.0 if after else 1.0))):
                    us.append(
                        {
                            "period": month.replace("-", ""),
                            "partnerCode": partner,
                            "cmdCode": hs6,
                            "primaryValue": 1.0,
                            "netWgt": kg,
                            "qtyUnitCode": 8,
                        }
                    )
            store.write_json_gz(f"{settings.raw_prefix}comtrade/imports_842/{month}.json.gz", us)
    for year in sorted({m[:4] for m in months}):
        rows = [
            {"period": m.replace("-", ""), "cmdCode": hs6, "primaryValue": 2e5 if m < "2018-07" else 6e5}
            for m in months
            if m.startswith(year)
            for hs6 in products
        ]
        store.write_json_gz(f"{settings.raw_prefix}comtrade/sg_X/{year}.json.gz", rows)
    cols = [
        {
            "key": f"{m[:4]} {['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][int(m[5:]) - 1]}",
            "value": v,
        }
        for m in months
        for v in ["1000"]
    ]
    for table, value in (("M451511", "5000"), ("M451501", "3000"), ("M700051", "1.35")):
        row = {"seriesNo": "1", "rowText": "x", "uoM": "", "columns": [{**c, "value": value} for c in cols]}
        store.write_json_gz(f"{settings.raw_prefix}singstat/{table}.json.gz", {"Data": {"row": [row]}})
    return products
