"""Run every batch step in order, logging each, and restart cleanly after a failure.

What it does:
    Two modes:
      * full      download (Census, Comtrade, SingStat) -> clean -> metrics -> detector ->
                  did_check -> singapore -> explain -> load_db -> ebs_snapshot
      * snapshot  restore the processed data from a snapshot file (no external
                  data API is called), then load_db -> ebs_snapshot. This is what a
                  fresh Sandbox session runs, because the Sandbox deletes
                  everything when a session ends.
    After each step succeeds a marker is written to processed/_steps/<step>.json.
    A re-run skips steps whose marker exists, so a failed step restarts without
    redoing earlier ones (Code standards, "Re-runnable pipeline"). Downloads always
    run because they only fetch what is missing. Every step is also recorded in
    the pipeline_runs table when the database is reachable.

Inputs:
    Settings from the environment (see .env.example).

Outputs:
    Everything the steps write, plus processed/_steps/*.json markers.

How to run:
    python -m batch.run_pipeline                  # full run, skipping finished steps
    python -m batch.run_pipeline --force          # redo every step
    python -m batch.run_pipeline --from metrics   # redo from one step onwards
    python -m batch.run_pipeline --mode snapshot --snapshot-url <url>
"""

from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime

from batch import (
    clean,
    detector,
    did_check,
    download_census,
    download_comtrade,
    download_singstat,
    ebs_snapshot,
    explain,
    load_db,
    metrics,
    singapore,
    snapshot,
)
from batch.storage_io import store
from config.logging_config import setup_logging
from config.settings import settings

log = logging.getLogger("run_pipeline")

# (name, function, always_run). Downloads always run: they skip files already stored.
FULL_STEPS: list[tuple[str, Callable[[], object], bool]] = [
    ("download_census", download_census.run, True),
    ("download_comtrade", download_comtrade.run, True),
    ("download_singstat", download_singstat.run, True),
    ("clean", clean.run, False),
    ("metrics", metrics.run, False),
    ("detector", detector.run, False),
    ("did_check", did_check.run, False),
    ("singapore", singapore.run, False),
    ("explain", explain.run, False),
    ("load_db", load_db.run, False),
    ("ebs_snapshot", ebs_snapshot.run, True),
]


def marker_key(step: str) -> str:
    """Storage key of a step's success marker."""
    return f"{settings.processed_prefix}_steps/{step}.json.gz"


def raw_count() -> int:
    """Number of raw data files stored (the Comtrade call log does not count as data)."""
    return sum(1 for k in store.list(settings.raw_prefix) if "/_calls/" not in k)


def record_run(step: str, status: str, started: datetime, detail: str = "") -> None:
    """Write one row to pipeline_runs; skipped quietly if the database is not reachable yet."""
    try:
        from config.database import connect

        with connect() as conn:
            conn.execute(
                "INSERT INTO pipeline_runs (step, status, started_at, finished_at, detail) VALUES (%s,%s,%s,now(),%s)",
                (step, status, started, detail[:1000]),
            )
    except Exception as exc:  # the table may not exist before load_db creates it
        log.debug("pipeline_runs not written: %s", exc)


def run_steps(steps: list[tuple[str, Callable[[], object], bool]], force: bool, from_step: str | None) -> None:
    """Run steps in order, skipping finished ones unless forced.

    Args:
        steps: (name, function, always_run) tuples.
        force: Redo every step.
        from_step: Redo this step and every later one.

    Raises:
        SystemExit: if a step fails; earlier markers stay, so the next run resumes there.
    """
    names = [s[0] for s in steps]
    if from_step and from_step not in names:
        raise SystemExit(f"Unknown step {from_step!r}; choose from {names}")
    redo_from = names.index(from_step) if from_step else len(names)
    for i, (name, func, always) in enumerate(steps):
        if not (force or always or i >= redo_from) and store.exists(marker_key(name)):
            log.info("Step %s: already done, skipping", name)
            continue
        started = datetime.now(UTC)
        t0 = time.monotonic()
        raw_before = raw_count() if name.startswith("download") else 0
        log.info("Step %s: starting", name)
        try:
            result = func()
        except Exception as exc:
            log.exception("Step %s failed", name)
            record_run(name, "failed", started, repr(exc))
            raise SystemExit(f"Pipeline stopped at {name}; fix the error and run again to resume") from exc
        seconds = time.monotonic() - t0
        # New raw files make every later result stale, so redo the rest of the steps.
        if name.startswith("download") and raw_count() > raw_before:
            redo_from = min(redo_from, i + 1)
        # download_comtrade returns False when the daily quota stopped it early.
        status = "partial" if result is False else "ok"
        store.write_json_gz(marker_key(name), {"finished_at": datetime.now(UTC).isoformat(), "status": status})
        record_run(name, status, started, f"{seconds:.0f}s")
        log.info("Step %s: %s in %.0fs", name, status, seconds)


def main() -> None:
    """Parse arguments and run the chosen mode."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=["full", "snapshot"], default="full")
    parser.add_argument("--force", action="store_true", help="redo every step")
    parser.add_argument("--from", dest="from_step", help="redo from this step onwards")
    parser.add_argument("--snapshot-url", default=settings.snapshot_url, help="snapshot file to restore")
    args = parser.parse_args()

    if args.mode == "snapshot":
        if not args.snapshot_url:
            raise SystemExit("--snapshot-url (or SNAPSHOT_URL) is required in snapshot mode")
        steps = [
            ("restore_snapshot", lambda: snapshot.restore(args.snapshot_url), False),
            ("load_db", load_db.run, False),
            ("ebs_snapshot", ebs_snapshot.run, True),
        ]
    else:
        steps = FULL_STEPS
    run_steps(steps, args.force, args.from_step)
    log.info("Pipeline finished (%s mode)", args.mode)


if __name__ == "__main__":
    setup_logging()
    main()
