"""Snapshot the batch server's EBS data volume after each pipeline run (Week 7).

What it does:
    Finds the data volume attached to this instance (device DATA_DEVICE, /dev/sdf),
    creates an EBS snapshot tagged Project=tradeshift, and deletes older snapshots
    so only the newest KEEP remain. Off EC2 (a laptop or Codespaces) it logs and
    does nothing.

Inputs:
    Instance metadata (IMDSv2) for the instance ID; LabRole permissions for EC2.

Outputs:
    One new EBS snapshot.

How to run:
    python -m batch.ebs_snapshot
"""

from __future__ import annotations

import logging
import os

import requests

from config.logging_config import setup_logging
from config.settings import settings

log = logging.getLogger("ebs_snapshot")

IMDS = "http://169.254.169.254/latest"
DATA_DEVICE = os.environ.get("DATA_DEVICE", "/dev/sdf")
KEEP = 3


def instance_id() -> str | None:
    """Return this EC2 instance's ID via IMDSv2, or None when not on EC2."""
    try:
        token = requests.put(
            f"{IMDS}/api/token", headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"}, timeout=2
        ).text
        return requests.get(
            f"{IMDS}/meta-data/instance-id", headers={"X-aws-ec2-metadata-token": token}, timeout=2
        ).text
    except requests.RequestException:
        return None


def run() -> str | None:
    """Create a snapshot of the data volume and prune old ones.

    Returns:
        The new snapshot ID, or None if not running on EC2.
    """
    iid = instance_id()
    if not iid:
        log.info("Not on EC2; skipping EBS snapshot")
        return None
    import boto3

    ec2 = boto3.client("ec2", region_name=settings.aws_region)
    volumes = ec2.describe_volumes(
        Filters=[
            {"Name": "attachment.instance-id", "Values": [iid]},
            {"Name": "attachment.device", "Values": [DATA_DEVICE]},
        ]
    )["Volumes"]
    if not volumes:
        log.warning("No volume at %s on %s; skipping EBS snapshot", DATA_DEVICE, iid)
        return None
    snap = ec2.create_snapshot(
        VolumeId=volumes[0]["VolumeId"],
        Description="TradeShift batch data volume after pipeline run",
        TagSpecifications=[{"ResourceType": "snapshot", "Tags": [{"Key": "Project", "Value": "tradeshift"}]}],
    )
    log.info("Started EBS snapshot %s of %s", snap["SnapshotId"], volumes[0]["VolumeId"])

    old = ec2.describe_snapshots(OwnerIds=["self"], Filters=[{"Name": "tag:Project", "Values": ["tradeshift"]}])
    for s in sorted(old["Snapshots"], key=lambda s: s["StartTime"], reverse=True)[KEEP:]:
        ec2.delete_snapshot(SnapshotId=s["SnapshotId"])
        log.info("Deleted old snapshot %s", s["SnapshotId"])
    return snap["SnapshotId"]


if __name__ == "__main__":
    setup_logging()
    run()
