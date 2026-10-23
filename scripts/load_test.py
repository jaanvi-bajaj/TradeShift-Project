"""Generate load on the web servers so the Auto Scaling Group scales out (Feature 6 test).

What it does:
    Sends concurrent requests to pages that do real work on every request (the
    detector re-runs in Python, the explorer and comparison build their tables).
    Average CPU across the web servers passes the 50% target, the CloudWatch alarm
    fires, and the Auto Scaling Group adds a server. Stop the script and the group
    scales back in. Keep the load moderate: the aim is to pass 50% CPU, not to make
    requests queue for minutes (then ALB health checks fail and servers get replaced).
    It also counts which instance answered each /health call (load-balancing test).

Inputs:
    --url      the ALB URL (stack output AppUrl)
    --minutes  how long to run (default 10)
    --workers  concurrent requests (default 10)

Outputs:
    Progress lines every 30 seconds, then a summary.

How to run:
    python scripts/load_test.py --url http://<alb-dns-name> --minutes 10

    From far away (e.g. a laptop in Asia) the requests spend most of their time on
    the network and CPU stays low. For the scaling demo, run the load in the same
    region, from AWS CloudShell:
        U=http://<alb-dns-name>; end=$((SECONDS+420)); while [ $SECONDS -lt $end ]; do
          seq 16 | xargs -P 16 -I{} curl -s -o /dev/null "$U/detector?event_id=S301_L1"; done
"""

from __future__ import annotations

import argparse
import collections
import json
import logging
import sys
import threading
import time
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)
log = logging.getLogger("load_test")

HEAVY_PATHS = ["/detector?event_id=S301_L1", "/explorer?hs6=847130", "/compare?mode=suppliers&a=CN&b=VN&hs6=940360"]


def worker(base: str, stop: float, counts: collections.Counter, lock: threading.Lock) -> None:
    """Request heavy pages until `stop`, counting results."""
    i = 0
    while time.time() < stop:
        path = HEAVY_PATHS[i % len(HEAVY_PATHS)]
        i += 1
        try:
            with urllib.request.urlopen(base + path, timeout=60) as resp:
                status = resp.status
        except Exception as exc:  # count failures too; a few are expected while scaling
            status = type(exc).__name__
        with lock:
            counts[status] += 1


def which_instances(base: str, n: int = 20) -> collections.Counter:
    """Call /health n times and count the instance IDs that answered."""
    seen: collections.Counter = collections.Counter()
    for _ in range(n):
        with urllib.request.urlopen(base + "/health", timeout=10) as resp:
            seen[json.loads(resp.read())["instance_id"]] += 1
    return seen


def main() -> None:
    """Parse arguments, report load balancing, then run the load."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True)
    parser.add_argument("--minutes", type=float, default=10)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()
    base = args.url.rstrip("/")

    log.info("Load balancing check, 20 calls to /health: %s", dict(which_instances(base)))
    stop = time.time() + args.minutes * 60
    counts: collections.Counter = collections.Counter()
    lock = threading.Lock()
    threads = [
        threading.Thread(target=worker, args=(base, stop, counts, lock), daemon=True) for _ in range(args.workers)
    ]
    for t in threads:
        t.start()
    while any(t.is_alive() for t in threads):
        time.sleep(30)
        with lock:
            log.info("Requests so far: %s", dict(counts))
    log.info("Done. Final counts: %s", dict(counts))
    log.info("Instances answering now: %s", dict(which_instances(base)))


if __name__ == "__main__":
    main()
