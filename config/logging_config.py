"""Shared logging setup.

What it does:
    Sends log lines to standard output in one format, so the CloudWatch agent on
    EC2 collects them unchanged (Code standards, "Logging, not print").

Inputs:
    LOG_LEVEL environment variable (default INFO).

Outputs:
    Configured root logger.

How to run:
    Not run directly. Call `setup_logging()` once at program start.
"""

from __future__ import annotations

import logging
import os
import sys


def setup_logging() -> None:
    """Configure the root logger to write timestamped lines to stdout."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
        force=True,
    )
