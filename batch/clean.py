"""Turn raw Census and Comtrade responses into one tidy monthly trade table.

What it does:
    1. Parses every raw month, keeps real countries only (drops Census regional
       groups and Comtrade "World"), and maps every supplier to ISO alpha-2.
    2. Keeps the top N suppliers per importer and product; smaller ones are summed
       into "ROW" (rest of world). Why: it keeps RDS small, and a supplier outside
       the top 15 cannot move a share by 3 points.
    3. Quantities: Census has none at HS6 (it reports 0), so US quantities are the
       net weights (kg) that the US reports to Comtrade, matched by product,
       supplier and month. Japan's come from the same Comtrade records. Only
       each product's most common unit is kept, so quantity shares compare like
       with like.
    4. Flags HS codes that start or stop at an HS revision (HS2017, HS2022), so
       event windows that cross a revision can be marked (Data rules).
    5. Writes a totals check: our country sum against the Census "all countries" row.
    6. Singapore: its total exports to the US (Comtrade), US imports of
       Singapore-origin goods (Census), and SingStat's official re-export and
       domestic-export totals converted to US$.

Inputs:
    raw/census/*.json.gz, raw/comtrade/imports_*/*.json.gz, raw/comtrade/sg_X/*.json.gz,
    raw/singstat/*.json.gz, data/countries.csv.

Outputs (in storage):
    processed/trade/<importer>/<hs2>.csv.gz   importer, supplier, hs6, month, value_usd, qty, qty_unit
    processed/products.csv.gz                 hs6, hs4, description, revised_in
    processed/singapore.csv.gz                hs6, month, sg_exports_usd, us_imports_sg_origin_usd, est_reexports_usd
    processed/singapore_official.csv.gz       month, rx_usd, dx_usd (SingStat, all products)
    processed/totals_check.csv.gz             month, census_total, country_sum, diff_pct

How to run:
    python -m batch.clean
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from batch.storage_io import store
from config.logging_config import setup_logging
from config.settings import settings

log = logging.getLogger("clean")

TIDY_COLUMNS = ["importer", "supplier", "hs6", "month", "value_usd", "qty", "qty_unit"]


def country_maps() -> tuple[dict[str, str], dict[str, str]]:
    """Return ({census_code: iso2}, {comtrade_code: iso2}) from data/countries.csv."""
    c = pd.read_csv(settings.country_file, dtype=str, keep_default_na=False)
    census = {r.census_code: r.iso2 for r in c.itertuples() if r.census_code}
    comtrade = {r.comtrade_code: r.iso2 for r in c.itertuples() if r.comtrade_code}
    return census, comtrade


def parse_census_month(table: list[list[str]], census_map: dict[str, str]) -> tuple[pd.DataFrame, float, dict]:
    """Convert one Census API table into tidy rows.

    Args:
        table: API response; the first row is the header.
        census_map: Census country code to ISO alpha-2.

    Returns:
        (tidy rows for real countries, the Census all-countries total, {hs6: description})
    """
    df = pd.DataFrame(table[1:], columns=table[0])
    df["value_usd"] = pd.to_numeric(df["GEN_VAL_MO"], errors="coerce").fillna(0.0)
    total = df.loc[df["CTY_CODE"] == "-", "value_usd"].sum()
    descriptions = dict(zip(df["I_COMMODITY"], df["I_COMMODITY_SDESC"]))
    # Real countries have a code in the Schedule C list; groups (e.g. 0003 EU, 1XXX) do not.
    df["supplier"] = df["CTY_CODE"].map(census_map)
    df = df[df["supplier"].notna() & (df["value_usd"] > 0)]
    out = pd.DataFrame(
        {
            "importer": "US",
            "supplier": df["supplier"],
            "hs6": df["I_COMMODITY"].str.zfill(6),
            "month": df["time"],
            "value_usd": df["value_usd"],
            # Census reports no quantities at HS6 (always 0); they come from Comtrade.
            "qty": np.nan,
            "qty_unit": np.nan,
        }
    )
    return out, float(total), descriptions


def parse_comtrade_rows(rows: list[dict], importer: str, comtrade_map: dict[str, str]) -> pd.DataFrame:
    """Convert Comtrade import records into tidy rows.

    Args:
        rows: Records from the Comtrade "data" array.
        importer: ISO alpha-2 of the reporting country.
        comtrade_map: Comtrade partner code to ISO alpha-2.

    Returns:
        Tidy rows; partner "World" (code 0) and unknown areas are dropped.
    """
    if not rows:
        return pd.DataFrame(columns=TIDY_COLUMNS)
    df = pd.DataFrame(rows)
    df["supplier"] = df["partnerCode"].astype(str).map(comtrade_map)
    df = df[df["supplier"].notna() & (df["primaryValue"] > 0)]
    period = df["period"].astype(str)
    return pd.DataFrame(
        {
            "importer": importer,
            "supplier": df["supplier"],
            "hs6": df["cmdCode"].astype(str).str.zfill(6),
            "month": period.str[:4] + "-" + period.str[4:6],
            "value_usd": df["primaryValue"].astype(float),
            # Net weight is reported in kg for almost every product, so it is the one
            # quantity measure that is comparable across suppliers.
            "qty": pd.to_numeric(df["netWgt"], errors="coerce").where(lambda q: q > 0),
            "qty_unit": "kg",
        }
    )


def spill_by_chapter(df: pd.DataFrame, work: Path, prefix: str = "") -> None:
    """Append rows to one working CSV per HS2 chapter on the batch server's EBS disk.

    Why: a whole decade of HS6-by-country data does not fit in a small
    instance's memory, but one chapter at a time does.

    Args:
        df: Tidy rows for one month.
        work: Working directory for chapter files.
        prefix: File name prefix, to keep separate tables apart (e.g. "qty_").
    """
    for hs2, part in df.groupby(df["hs6"].str[:2]):
        path = work / f"{prefix}{hs2}.csv"
        part.to_csv(path, mode="a", header=not path.exists(), index=False)


def top_suppliers(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Keep each product's top-n suppliers by total value and sum the rest into "ROW".

    Args:
        df: Tidy rows for one or more products of one importer.
        n: Number of named suppliers to keep per product.

    Returns:
        Rows with at most n + 1 suppliers per (importer, hs6, month).
    """
    totals = df.groupby(["importer", "hs6", "supplier"])["value_usd"].sum().reset_index()
    totals["rank"] = totals.groupby(["importer", "hs6"])["value_usd"].rank(ascending=False, method="first")
    keep = totals.loc[totals["rank"] <= n, ["importer", "hs6", "supplier"]]
    merged = df.merge(keep.assign(keep=True), on=["importer", "hs6", "supplier"], how="left")
    named = merged[merged["keep"].eq(True)].drop(columns="keep")
    rest = merged[merged["keep"].isna()]
    if rest.empty:
        return named
    row = rest.groupby(["importer", "hs6", "month"], as_index=False).agg(
        value_usd=("value_usd", "sum"), qty=("qty", lambda q: q.sum(min_count=1)), qty_unit=("qty_unit", "first")
    )
    return pd.concat([named, row.assign(supplier="ROW")], ignore_index=True)


def modal_unit_quantities(df: pd.DataFrame) -> pd.DataFrame:
    """Blank out quantities not in each product's most common unit.

    Why: a quantity share only makes sense if every supplier is counted in the
    same unit; value alone can move with prices (Diversion detector, quantity check).

    Args:
        df: Tidy rows.

    Returns:
        Same rows; qty is NaN where the unit differs from the product's modal unit.
    """
    has_qty = df.dropna(subset=["qty", "qty_unit"])
    if has_qty.empty:
        return df
    modal = has_qty.groupby(["importer", "hs6"])["qty_unit"].agg(lambda s: s.value_counts().index[0])
    df = df.join(modal.rename("modal_unit"), on=["importer", "hs6"])
    df.loc[df["qty_unit"] != df["modal_unit"], "qty"] = np.nan
    df["qty_unit"] = df["modal_unit"]
    return df.drop(columns="modal_unit")


def revision_flags(df: pd.DataFrame) -> pd.Series:
    """Return {hs6: "2017-01"} for codes that start or stop at an HS revision date.

    Why: in HS2017 and HS2022 some codes were split or merged, so a series that
    starts or ends exactly at a revision is a code change, not a trade change.

    Args:
        df: US tidy rows (the main series).

    Returns:
        Series indexed by hs6 with the revision month, for flagged codes only.
    """
    span = df.groupby("hs6")["month"].agg(["min", "max"])
    first, last = df["month"].min(), df["month"].max()
    flags = {}
    for rev in settings.hs_revision_dates:
        y, m = map(int, rev.split("-"))
        before = f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"
        starts = span.index[(span["min"] == rev) & (rev > first)]
        stops = span.index[(span["max"] == before) & (before < last)]
        for code in list(starts) + list(stops):
            flags.setdefault(code, rev)
    return pd.Series(flags, name="revised_in", dtype=str)


def attach_us_quantities(us: pd.DataFrame, qty: pd.DataFrame) -> pd.DataFrame:
    """Put Comtrade net weights onto the Census value rows for the same product, supplier and month.

    Args:
        us: Census tidy rows for one chapter (qty empty).
        qty: Comtrade US import rows for the same chapter.

    Returns:
        The Census rows with qty (kg) where Comtrade has a matching record.
    """
    if qty.empty:
        return us
    q = qty.groupby(["hs6", "supplier", "month"], as_index=False)["qty"].sum(min_count=1)
    out = us.drop(columns=["qty", "qty_unit"]).merge(q, on=["hs6", "supplier", "month"], how="left")
    out["qty_unit"] = np.where(out["qty"].notna(), "kg", None)
    return out


def singstat_series(table: dict, fx: pd.Series) -> pd.Series:
    """Turn one SingStat row (S$ million by month) into US dollars by month.

    Args:
        table: The stored SingStat JSON for one table.
        fx: S$ per US$, indexed by month.

    Returns:
        US$ values indexed by YYYY-MM.
    """
    row = table["Data"]["row"][0]
    months = pd.to_datetime([c["key"] for c in row["columns"]], format="%Y %b").strftime("%Y-%m")
    sgd_m = pd.Series([float(c["value"]) for c in row["columns"]], index=months)
    return 1e6 * sgd_m / fx.reindex(sgd_m.index)


def singapore_tables(sg_origin: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the HS6 Singapore table and the official totals table.

    Why the estimate: Comtrade has no re-export split for Singapore, and SingStat
    splits only totals. Singapore's exports to the US (all goods, Comtrade) minus US
    imports of Singapore-origin goods (Census) approximates what Singapore passed on
    from elsewhere. The two sources value goods slightly differently (FOB vs customs
    value) and ship-to-arrival timing differs, so small or negative gaps are noise.

    Args:
        sg_origin: Census rows of US imports whose origin is Singapore (hs6, month, value_usd).

    Returns:
        (HS6 monthly table, monthly official totals).
    """
    exports = []
    for key in store.list(f"{settings.raw_prefix}comtrade/sg_X/"):
        rows = store.read_json_gz(key)
        if rows:
            d = pd.DataFrame(rows)
            period = d["period"].astype(str)
            exports.append(
                pd.DataFrame(
                    {
                        "hs6": d["cmdCode"].astype(str).str.zfill(6),
                        "month": period.str[:4] + "-" + period.str[4:6],
                        "sg_exports_usd": d["primaryValue"].astype(float),
                    }
                )
            )
    ex = (
        pd.concat(exports).groupby(["hs6", "month"], as_index=False)["sg_exports_usd"].sum()
        if exports
        else pd.DataFrame(columns=["hs6", "month", "sg_exports_usd"])
    )
    origin = (
        sg_origin.groupby(["hs6", "month"], as_index=False)["value_usd"]
        .sum()
        .rename(columns={"value_usd": "us_imports_sg_origin_usd"})
    )
    hs6 = ex.merge(origin, on=["hs6", "month"], how="outer").fillna(0.0)
    # Only months both sources have published; otherwise the "estimate" for a month
    # Census has not released yet would be all of Singapore's exports.
    both = set(ex["month"]) & set(origin["month"])
    hs6 = hs6[hs6["month"].isin(both)]
    hs6 = hs6[hs6["hs6"].str.len() == 6]
    hs6["est_reexports_usd"] = (hs6["sg_exports_usd"] - hs6["us_imports_sg_origin_usd"]).clip(lower=0)

    official = pd.DataFrame(columns=["month", "rx_usd", "dx_usd"])
    keys = {t: f"{settings.raw_prefix}singstat/{t}.json.gz" for t in ("M451511", "M451501", "M700051")}
    if all(store.exists(k) for k in keys.values()):
        fx_row = store.read_json_gz(keys["M700051"])["Data"]["row"][0]
        fx = pd.Series(
            [float(c["value"]) for c in fx_row["columns"]],
            index=pd.to_datetime([c["key"] for c in fx_row["columns"]], format="%Y %b").strftime("%Y-%m"),
        )
        official = pd.DataFrame(
            {
                "rx_usd": singstat_series(store.read_json_gz(keys["M451511"]), fx),
                "dx_usd": singstat_series(store.read_json_gz(keys["M451501"]), fx),
            }
        )
        official = official[official.index >= settings.start_month].dropna().rename_axis("month").reset_index()
    return hs6, official


def run() -> None:
    """Clean every raw file and write the processed tables."""
    census_map, comtrade_map = country_maps()
    work = settings.work_dir / "chapters"
    shutil.rmtree(work, ignore_errors=True)  # re-runnable: always rebuild from raw
    work.mkdir(parents=True)

    # Pass 1: parse each raw month and spill to chapter files.
    descriptions: dict[str, str] = {}
    totals, sg_origin = [], []
    for key in store.list(f"{settings.raw_prefix}census/"):
        tidy, total, desc = parse_census_month(store.read_json_gz(key), census_map)
        descriptions.update(desc)
        totals.append({"month": key[-15:-8], "census_total": total, "country_sum": tidy["value_usd"].sum()})
        sg_origin.append(tidy.loc[tidy["supplier"] == "SG", ["hs6", "month", "value_usd"]])
        spill_by_chapter(tidy, work)
    log.info("Parsed %d Census months", len(totals))

    importer = settings.second_importer_iso2
    reporter = pd.read_csv(settings.country_file, dtype=str).set_index("iso2").loc[importer, "comtrade_code"]
    jp_keys = store.list(f"{settings.raw_prefix}comtrade/imports_{reporter}/")
    for key in jp_keys:
        spill_by_chapter(parse_comtrade_rows(store.read_json_gz(key), importer, comtrade_map), work)
    us_qty_keys = store.list(f"{settings.raw_prefix}comtrade/imports_{settings.usa_comtrade_code}/")
    for key in us_qty_keys:
        spill_by_chapter(parse_comtrade_rows(store.read_json_gz(key), "US", comtrade_map), work, prefix="qty_")
    log.info("Parsed %d Comtrade files for %s and %d US quantity files", len(jp_keys), importer, len(us_qty_keys))

    # Pass 2: one chapter at a time, top suppliers, units, then save.
    revised = []
    dtypes = {"hs6": str, "supplier": str, "qty_unit": str, "month": str}
    for path in sorted(p for p in work.glob("*.csv") if not p.name.startswith("qty_")):
        df = pd.read_csv(path, dtype=dtypes)
        qty_path = work / f"qty_{path.name}"
        if qty_path.exists():
            us = attach_us_quantities(df[df["importer"] == "US"], pd.read_csv(qty_path, dtype=dtypes))
            df = pd.concat([us, df[df["importer"] != "US"]], ignore_index=True)
        df = df.groupby(TIDY_COLUMNS[:4] + ["qty_unit"], as_index=False, dropna=False)[["value_usd", "qty"]].sum(
            min_count=1
        )
        df = modal_unit_quantities(df)
        df = top_suppliers(df, settings.top_suppliers)
        revised.append(revision_flags(df[df["importer"] == "US"]))
        for imp, part in df.groupby("importer"):
            store.write_df(f"{settings.processed_prefix}trade/{imp}/{path.stem}.csv.gz", part[TIDY_COLUMNS])

    products = pd.DataFrame({"hs6": list(descriptions), "description": list(descriptions.values())})
    products = products[products["hs6"].str.len() == 6]
    products["hs4"] = products["hs6"].str[:4]
    products = products.merge(pd.concat(revised).rename("revised_in"), left_on="hs6", right_index=True, how="left")
    store.write_df(f"{settings.processed_prefix}products.csv.gz", products)

    t = pd.DataFrame(totals)
    if not t.empty:
        t["diff_pct"] = 100 * (t["country_sum"] - t["census_total"]) / t["census_total"]
    store.write_df(f"{settings.processed_prefix}totals_check.csv.gz", t)

    sg_hs6, sg_official = singapore_tables(
        pd.concat(sg_origin) if sg_origin else pd.DataFrame(columns=["hs6", "month", "value_usd"])
    )
    store.write_df(f"{settings.processed_prefix}singapore.csv.gz", sg_hs6)
    store.write_df(f"{settings.processed_prefix}singapore_official.csv.gz", sg_official)
    log.info("Clean finished")


if __name__ == "__main__":
    setup_logging()
    run()
