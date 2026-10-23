"""Shared pytest setup.

What it does: makes the repo root importable and points storage at a temporary
folder, so tests never touch S3 or the real local_data directory.
Inputs: none. Outputs: pytest fixtures.
How to run: pytest (from the repo root).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Tests must never use real credentials or cloud storage.
os.environ["STORAGE_MODE"] = "local"
os.environ.pop("S3_BUCKET", None)
# Settings are read once at import, so the temporary folders must be set before any
# project module is imported (conftest runs first).
_TMP = Path(tempfile.mkdtemp(prefix="tradeshift-test-"))
os.environ["LOCAL_DATA_DIR"] = str(_TMP / "data")
os.environ["WORK_DIR"] = str(_TMP / "work")
os.environ.setdefault("CENSUS_API_KEY", "test-key-not-used")
