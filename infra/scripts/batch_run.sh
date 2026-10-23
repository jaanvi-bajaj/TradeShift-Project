#!/bin/bash
# Prepare the batch server's EBS data volume and run the pipeline (called by CloudFormation user data).
#
# What it does: formats the data volume the first time (never again), mounts it at /data,
#   then runs batch/run_pipeline.py in the chosen mode with settings from /etc/tradeshift.env.
# Inputs:  $1 mode: snapshot (default) | full; $2 optional --force to redo finished steps
# Outputs: data in S3 and RDS; pipeline log in /var/log/tradeshift/pipeline.log
# How to run: sudo bash infra/scripts/batch_run.sh snapshot [--force]
set -euo pipefail
MODE="${1:-snapshot}"
FORCE="${2:-}"
DEV=/dev/sdf
# On Nitro instances the volume appears as NVMe; Amazon Linux links /dev/sdf to it.
for i in $(seq 1 30); do [ -e "$DEV" ] && break; sleep 2; done
if ! blkid "$DEV" >/dev/null 2>&1; then
  mkfs -t xfs "$DEV"     # only when the volume is blank
fi
mkdir -p /data
grep -q " /data " /etc/fstab || echo "$DEV /data xfs defaults,nofail 0 2" >> /etc/fstab
mountpoint -q /data || mount /data
mkdir -p /data/work

cd /opt/tradeshift
set -a; . /etc/tradeshift.env; set +a
/opt/tradeshift/venv/bin/python -m batch.run_pipeline --mode "$MODE" $FORCE 2>&1 | tee -a /var/log/tradeshift/pipeline.log
