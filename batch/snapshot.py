"""Export the pipeline's data as split files for a GitHub release, and restore them into a new stack.

What it does:
    The AWS Academy Sandbox deletes every resource when a session ends, so the
    data cannot live only in S3 and RDS. After a full pipeline run, `export` packs
    a storage prefix into a gzipped tar, splits it into parts below 95 MB (GitHub
    refuses files over 100 MB in a repository, and smaller parts download and
    retry more reliably) and writes a small manifest listing every part with its
    SHA-256. On every new stack, the batch server `restore`s from the manifest:
    it downloads each part, checks each checksum, and writes the files back to S3.
    No trade-data API is called during a rebuild or the demo (Data rules).

    Two snapshots are made:
      * processed  (processed/): what a new stack needs; restored every session.
      * raw        (raw/): the API responses, kept so nobody downloads them again.

Inputs:
    export: files in storage under the chosen prefix.
    restore: a manifest URL (or path); optionally SNAPSHOT_SHA256 = SHA-256 of the manifest.

Outputs:
    export: dist/tradeshift-<name>.json and dist/tradeshift-<name>.tar.gz.partNN
    restore: the same keys written back into storage.

How to run:
    python -m batch.snapshot export processed
    python -m batch.snapshot export raw
    python -m batch.snapshot restore <manifest-url>
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import tarfile
from urllib.parse import urljoin

import requests

from batch.storage_io import store
from config.logging_config import setup_logging
from config.settings import REPO_ROOT, settings

log = logging.getLogger("snapshot")

DIST = REPO_ROOT / "dist"
PART_BYTES = 95 * 1000 * 1000  # below GitHub's 100 MB limit for files
PREFIXES = {"processed": settings.processed_prefix, "raw": settings.raw_prefix}


def sha256(data: bytes) -> str:
    """Hex SHA-256 of some bytes."""
    return hashlib.sha256(data).hexdigest()


def export(name: str = "processed") -> str:
    """Pack one storage prefix into split parts plus a manifest under dist/.

    Args:
        name: "processed" or "raw".

    Returns:
        Path of the manifest file.
    """
    DIST.mkdir(exist_ok=True)
    buf = io.BytesIO()
    files = 0
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for key in store.list(PREFIXES[name]):
            if "/_steps/" in key:
                continue  # step markers belong to one environment, not the data
            data = store.read_bytes(key)
            info = tarfile.TarInfo(key)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
            files += 1
    blob = buf.getvalue()
    base = f"tradeshift-{name}.tar.gz"
    for old in DIST.glob(f"{base}.part*"):
        old.unlink()
    parts = []
    for i in range(0, len(blob), PART_BYTES):
        chunk = blob[i : i + PART_BYTES]
        part_name = f"{base}.part{len(parts):02d}"
        (DIST / part_name).write_bytes(chunk)
        parts.append({"name": part_name, "bytes": len(chunk), "sha256": sha256(chunk)})
    manifest = {"name": name, "files": files, "bytes": len(blob), "sha256": sha256(blob), "parts": parts}
    path = DIST / f"tradeshift-{name}.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    log.info(
        "Wrote %s: %d files, %.1f MB in %d parts; manifest sha256 %s",
        path,
        files,
        len(blob) / 1e6,
        len(parts),
        sha256(path.read_bytes()),
    )
    return str(path)


def fetch(location: str) -> bytes:
    """Read a local file or download a URL, with a few retries."""
    if os.path.exists(location):
        with open(location, "rb") as fh:
            return fh.read()
    for attempt in range(1, 4):
        try:
            resp = requests.get(location, timeout=600)
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as exc:
            log.warning("Download %s failed (attempt %d): %s", location, attempt, exc)
    raise SystemExit(f"Could not download {location}")


def restore(manifest_url: str) -> int:
    """Download every part listed in a manifest, check it, and write the files to storage.

    Parts are joined into one file on the work disk (the batch server's EBS volume)
    rather than in memory, so a snapshot of several hundred MB fits a small server.

    Args:
        manifest_url: URL or path of tradeshift-<name>.json. Parts are fetched from
            the same folder (for a GitHub release, the same release).

    Returns:
        Number of files restored.
    """
    raw_manifest = fetch(manifest_url)
    expected = os.environ.get("SNAPSHOT_SHA256", "").strip()
    if expected and expected != sha256(raw_manifest):
        raise SystemExit(f"Snapshot manifest checksum mismatch: expected {expected}, got {sha256(raw_manifest)}")
    manifest = json.loads(raw_manifest)
    settings.work_dir.mkdir(parents=True, exist_ok=True)
    joined = settings.work_dir / f"restore-{manifest['name']}.tar.gz"
    whole = hashlib.sha256()
    with joined.open("wb") as out:
        for part in manifest["parts"]:
            location = (
                os.path.join(os.path.dirname(manifest_url), part["name"])
                if os.path.exists(manifest_url)
                else urljoin(manifest_url, part["name"])
            )
            chunk = fetch(location)
            if sha256(chunk) != part["sha256"]:
                raise SystemExit(f"Checksum mismatch for {part['name']}")  # altered or truncated download
            whole.update(chunk)
            out.write(chunk)
    if whole.hexdigest() != manifest["sha256"]:
        raise SystemExit("Snapshot checksum mismatch after joining the parts")
    count = 0
    with tarfile.open(joined, mode="r:gz") as tar:
        for member in tar:
            # Only plain files under our two prefixes, never paths that climb out of them.
            if not member.isfile() or not member.name.startswith(tuple(PREFIXES.values())):
                continue
            if ".." in member.name.split("/"):
                continue
            store.write_bytes(member.name, tar.extractfile(member).read())
            count += 1
    log.info("Restored %d files (%.1f MB from %d parts)", count, manifest["bytes"] / 1e6, len(manifest["parts"]))
    joined.unlink()
    return count


if __name__ == "__main__":
    setup_logging()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_export = sub.add_parser("export")
    p_export.add_argument("name", choices=sorted(PREFIXES), nargs="?", default="processed")
    p_restore = sub.add_parser("restore")
    p_restore.add_argument("url")
    args = parser.parse_args()
    if args.cmd == "export":
        export(args.name)
    else:
        restore(args.url)
