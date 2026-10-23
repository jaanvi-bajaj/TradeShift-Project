"""End-to-end smoke test: synthetic raw data -> every pipeline step -> database -> every page.

What it does: proves the pieces fit together. The processing steps always run;
the database and web-page part runs only when TRADESHIFT_TEST_DB=1 and DB_HOST/
DB_PORT/DB_USER point at a disposable local PostgreSQL (never RDS).
How to run:
    pytest tests/test_pipeline_smoke.py
    TRADESHIFT_TEST_DB=1 DB_HOST=127.0.0.1 DB_PORT=55432 DB_USER=tradeshift pytest tests/test_pipeline_smoke.py
"""

from __future__ import annotations

import io
import json
import os

import pytest

from batch import clean, detector, did_check, explain, metrics, singapore
from batch.storage_io import store
from config.settings import settings
from tests.fake_data import write_fake_raw

P = settings.processed_prefix


@pytest.fixture(scope="module")
def processed():
    """Run every processing step once on the synthetic data."""
    products = write_fake_raw()
    clean.run()
    metrics.run()
    detector.run()
    did_check.run()
    singapore.run()
    explain.run()
    return products


def test_processing_outputs(processed):
    for key in [
        "products.csv.gz",
        "event_shares.csv.gz",
        "event_products.csv.gz",
        "signals_explained.csv.gz",
        "did_results.csv.gz",
        "singapore_lens.csv.gz",
        "totals_check.csv.gz",
    ]:
        assert store.exists(P + key), key
    trade = metrics.load_trade("US")
    # The EU group row and the all-countries total must not be counted as suppliers.
    assert set(trade["supplier"]) <= {"CN", "VN", "KR", "MX", "TH", "CA"}
    totals = store.read_df(P + "totals_check.csv.gz")
    assert totals["diff_pct"].abs().max() < 0.01  # country sum matches the Census total


def test_detector_finds_the_planted_shift(processed):
    signals = store.read_df(P + "signals_explained.csv.gz", dtype={"hs6": str})
    s301 = signals[signals["event_id"] == "S301_L1"]
    assert not s301.empty
    assert set(s301["loser"]) == {"CN"} and set(s301["gainer"]) == {"VN"}
    assert s301["explanation"].str.contains("China's share").all()
    # US quantities come from Comtrade and move the same way, so the flag is higher confidence.
    assert set(s301["confidence"]) == {"higher"}


@pytest.mark.skipif(os.environ.get("TRADESHIFT_TEST_DB") != "1", reason="needs a disposable local PostgreSQL")
def test_load_db_and_every_page(processed):
    from batch import load_db

    load_db.run()
    load_db.run()  # re-runnable: a second load must not duplicate rows
    from app.app import create_app
    from config.database import connect

    with connect() as conn:
        n1 = conn.execute("SELECT COUNT(*) FROM trade_monthly").fetchone()[0]
        n_events = conn.execute("SELECT COUNT(*) FROM tariff_events").fetchone()[0]
    assert n1 > 0 and n_events == 10

    app = create_app()
    client = app.test_client()
    routes = app.url_map.bind("localhost")
    hs6 = sorted(processed)[0]
    for url in [
        "/",
        "/health",
        f"/explorer?hs6={hs6}",
        "/detector?event_id=S301_L1",
        "/detector?event_id=",
        f"/concentration?hs6={hs6}",
        "/movers",
        "/singapore",
        "/compare",
        "/compare?mode=importers",
        f"/compare?mode=products&a={hs6}&b={sorted(processed)[1]}",
        "/history",
        "/notes",
        "/search?go=1&hs=84",
        f"/source/S301_L1/{hs6}",
        f"/api/products?q={hs6[:4]}",
    ]:
        try:
            routes.match(url.split("?")[0])
        except Exception:
            continue  # page not built yet in this branch
        resp = client.get(url)
        assert resp.status_code == 200, (url, resp.status_code)
        assert b"e+0" not in resp.data, url  # Feature 1: no raw scientific notation
    assert json.loads(client.get("/health").data)["database"] == "ok"

    if not {"history.save", "notes.add", "search.page"} <= set(app.view_functions):
        return  # Features 3-5 not built yet in this branch
    # Feature 3 + 4: save an analysis, reopen it, add a note to it.
    page = client.get(f"/explorer?hs6={hs6}").data.decode()
    payload = page.split('name="analysis" value="', 1)[1].split('"', 1)[0]
    import html

    resp = client.post("/history/save", data={"analysis": html.unescape(payload), "title": "Smoke test"})
    assert resp.status_code == 302
    saved = client.get(resp.headers["Location"])
    assert saved.status_code == 200 and b"Smoke test" in saved.data
    analysis_id = resp.headers["Location"].split("/history/")[1].split("?")[0]
    resp = client.post(
        "/notes",
        data={
            "target_type": "analysis",
            "target_id": analysis_id,
            "body": "note text",
            "hs6": hs6,
            "next": f"/history/{analysis_id}",
        },
    )
    assert resp.status_code == 302
    assert b"note text" in client.get(f"/history/{analysis_id}").data
    # Feature 5: search by HS code prefix finds both.
    found = client.get(f"/search?go=1&hs={hs6[:4]}").data
    assert b"Smoke test" in found and b"note text" in found

    # Export, wipe (as a Sandbox session end does), import: everything comes back once.
    exported = client.get("/history/export")
    assert exported.status_code == 200 and exported.mimetype == "application/zip"
    with connect(autocommit=True) as conn:
        conn.execute("TRUNCATE analyses, notes")
    resp = client.post(
        "/history/import",
        data={"bundle": (io.BytesIO(exported.data), "export.zip")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 302 and "1+analyses" in resp.headers["Location"]
    assert b"note text" in client.get(f"/history/{analysis_id}").data
    again = client.post(
        "/history/import",
        data={"bundle": (io.BytesIO(exported.data), "export.zip")},
        content_type="multipart/form-data",
    )
    assert "0+analyses+and+0+notes" in again.headers["Location"]
    bad = client.post(
        "/history/import", data={"bundle": (io.BytesIO(b"not a zip"), "x.zip")}, content_type="multipart/form-data"
    )
    assert "error=" in bad.headers["Location"]
