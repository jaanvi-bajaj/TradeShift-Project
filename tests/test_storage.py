"""Unit tests for app/storage.py and batch/storage_io.py (Feature 3: saved analysis reopens identically).

How to run: pytest tests/test_storage.py
"""

from __future__ import annotations

import pandas as pd

from app import storage
from batch.storage_io import Store


def sample_analysis() -> dict:
    return {
        "view": "explorer",
        "title": "US imports of HS 8450.20",
        "params": {"importer": "US", "hs6": "845020"},
        "meta": {"hs6": "845020", "importer": "US", "supplier": "", "event_id": ""},
        "summary": ["China's share fell from 62.0% to 41.0%."],
        "charts": [
            {
                "id": "share",
                "type": "line",
                "title": "Share",
                "labels": ["2018-01"],
                "datasets": [{"label": "China", "data": [61.9], "color": "#000"}],
                "y_format": "pct",
                "marks": [],
            }
        ],
        "tables": [
            {
                "title": "Suppliers",
                "columns": [{"key": "name", "label": "Supplier"}, {"key": "v", "label": "Value", "format": "usd_m"}],
                "rows": [{"name": "China | PRC", "v": 4.07e9}],
            }
        ],
        "sources": [{"label": "Census", "url": "/source/explorer/845020"}],
    }


def test_saved_analysis_round_trips_identically(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "store", Store("local", "", tmp_path))
    a = sample_analysis()
    key = storage.save(a, "00000000-0000-0000-0000-000000000001")
    assert key.startswith("analyses/") and key.endswith(".md")
    loaded, text = storage.load(key)
    assert loaded == a  # identical inputs, results and chart data
    # The Markdown is readable on its own, with formatted numbers.
    assert "# US imports of HS 8450.20" in text
    assert "US$4,070.0m" in text
    assert "China / PRC" in text  # pipes are escaped so the table stays valid


def test_local_store_round_trip(tmp_path):
    s = Store("local", "", tmp_path)
    s.write_json_gz("raw/x/1.json.gz", [1, 2, 3])
    assert s.exists("raw/x/1.json.gz")
    assert s.read_json_gz("raw/x/1.json.gz") == [1, 2, 3]
    df = pd.DataFrame({"a": [1, 2]})
    s.write_df("processed/t.csv.gz", df)
    assert s.read_df("processed/t.csv.gz").equals(df)
    assert s.list("raw/") == ["raw/x/1.json.gz"]


def test_snapshot_splits_and_restores(tmp_path, monkeypatch):
    """Snapshot export splits into parts with checksums; restore joins, checks and writes them back."""
    import os

    import pytest

    from batch import snapshot

    src = Store("local", "", tmp_path / "src")
    for i in range(5):
        src.write_bytes(f"processed/t{i}.bin", os.urandom(4000))  # random bytes do not compress
    src.write_bytes("processed/_steps/clean.json.gz", b"x")  # environment-specific, must be left out
    monkeypatch.setattr(snapshot, "store", src)
    monkeypatch.setattr(snapshot, "DIST", tmp_path / "dist")
    monkeypatch.setattr(snapshot, "PART_BYTES", 5000)
    manifest = snapshot.export("processed")
    parts = sorted((tmp_path / "dist").glob("*.part*"))
    assert len(parts) >= 4

    dst = Store("local", "", tmp_path / "dst")
    monkeypatch.setattr(snapshot, "store", dst)
    assert snapshot.restore(manifest) == 5
    assert dst.read_bytes("processed/t3.bin") == src.read_bytes("processed/t3.bin")
    assert not dst.exists("processed/_steps/clean.json.gz")

    parts[1].write_bytes(b"tampered")
    with pytest.raises(SystemExit):
        snapshot.restore(manifest)
