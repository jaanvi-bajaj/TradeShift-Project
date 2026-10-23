"""Read and write pipeline files in S3, or in a local folder during development.

What it does:
    Gives every batch step the same four calls (exists, read, write, list) whether
    files live in S3 (on AWS) or under LOCAL_DATA_DIR (Codespaces or a laptop).
    Keys look the same in both modes, e.g. "raw/census/2018-07.json.gz".

Inputs:
    settings.storage_mode, settings.s3_bucket, settings.local_dir.

Outputs:
    Files in S3 or on local disk.

How to run:
    Not run directly. `from batch.storage_io import store`.
"""

from __future__ import annotations

import gzip
import io
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from config.settings import settings

log = logging.getLogger(__name__)


class Store:
    """A tiny key/value file store backed by S3 or a local directory."""

    def __init__(self, mode: str, bucket: str, local_dir: Path) -> None:
        """Create the store.

        Args:
            mode: "s3" or "local".
            bucket: S3 bucket name (used when mode is "s3").
            local_dir: Root folder (used when mode is "local").
        """
        self.mode = mode
        self.bucket = bucket
        self.local_dir = local_dir
        self._s3 = None
        if mode == "s3":
            import boto3  # imported here so local runs do not need AWS credentials

            self._s3 = boto3.client("s3", region_name=settings.aws_region)

    def exists(self, key: str) -> bool:
        """Return True if a file with this key is already stored."""
        if self._s3 is None:
            return (self.local_dir / key).exists()
        try:
            self._s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except self._s3.exceptions.ClientError:
            return False

    def write_bytes(self, key: str, data: bytes) -> None:
        """Store raw bytes under `key`, replacing any existing file."""
        if self._s3 is None:
            path = self.local_dir / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        else:
            self._s3.put_object(Bucket=self.bucket, Key=key, Body=data)

    def read_bytes(self, key: str) -> bytes:
        """Return the bytes stored under `key`."""
        if self._s3 is None:
            return (self.local_dir / key).read_bytes()
        return self._s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def list(self, prefix: str) -> list[str]:
        """Return every key that starts with `prefix`, sorted."""
        if self._s3 is None:
            root = self.local_dir / prefix
            base = root if root.is_dir() else root.parent
            if not base.exists():
                return []
            keys = [str(p.relative_to(self.local_dir)) for p in base.rglob("*") if p.is_file()]
            return sorted(k for k in keys if k.startswith(prefix))
        keys: list[str] = []
        for page in self._s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
            keys += [obj["Key"] for obj in page.get("Contents", [])]
        return sorted(keys)

    # Convenience wrappers. Raw API responses are gzipped JSON; tables are gzipped CSV.

    def write_json_gz(self, key: str, payload: Any) -> None:
        """Store `payload` as gzipped JSON."""
        self.write_bytes(key, gzip.compress(json.dumps(payload).encode()))

    def read_json_gz(self, key: str) -> Any:
        """Load gzipped JSON stored under `key`."""
        return json.loads(gzip.decompress(self.read_bytes(key)))

    def write_df(self, key: str, df: pd.DataFrame) -> None:
        """Store a DataFrame as gzipped CSV (readable by anyone, no extra libraries)."""
        buf = io.BytesIO()
        df.to_csv(buf, index=False, compression={"method": "gzip", "mtime": 0})
        self.write_bytes(key, buf.getvalue())
        log.info("Wrote %s (%d rows)", key, len(df))

    def read_df(self, key: str, **kwargs: Any) -> pd.DataFrame:
        """Load a gzipped CSV stored under `key` into a DataFrame."""
        return pd.read_csv(io.BytesIO(self.read_bytes(key)), compression="gzip", **kwargs)


store = Store(settings.storage_mode, settings.s3_bucket, settings.local_dir)
