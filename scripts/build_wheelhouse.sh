#!/bin/bash
# Build the offline wheel bundle that EC2 servers and CI install from.
#
# What it does: downloads every pinned package in requirements-dev.txt (which includes
#   requirements.txt) as Linux x86_64 wheels for Python 3.11, from whatever package index
#   pip is configured to use, then packs them into dist/wheelhouse-py311-x86_64.tar.gz
#   with a SHA-256 file. Upload both to the GitHub release (see RUNBOOK.md, Part A).
# Why: servers then install with --no-index, so a deploy never depends on a package
#   registry being reachable, and every server gets exactly the same versions.
# Inputs: requirements-dev.txt; a configured pip index (PIP_INDEX_URL or pip.conf).
# Outputs: dist/wheelhouse-py311-x86_64.tar.gz and .sha256
# How to run: bash scripts/build_wheelhouse.sh
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=dist/wheelhouse
rm -rf "$OUT" && mkdir -p "$OUT"
python3 -m pip download --only-binary=:all: --implementation cp --python-version 3.11 \
  --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 \
  --platform manylinux_2_24_x86_64 --platform manylinux_2_28_x86_64 \
  -r requirements-dev.txt -d "$OUT"
tar -czf dist/wheelhouse-py311-x86_64.tar.gz -C "$OUT" .
(cd dist && shasum -a 256 wheelhouse-py311-x86_64.tar.gz > wheelhouse-py311-x86_64.tar.gz.sha256)
cat dist/wheelhouse-py311-x86_64.tar.gz.sha256
