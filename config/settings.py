"""All TradeShift settings in one place.

What it does:
    Reads every setting from environment variables, with safe defaults for local
    development. Thresholds and dates live here so no other file hard-codes them
    (Code standards, "No hard-coded values").

Inputs:
    Environment variables. Locally they can come from a .env file in the repo root;
    on EC2 they come from /etc/tradeshift.env, written by CloudFormation user data.

Outputs:
    A single frozen `settings` object imported by batch jobs and the web app.

How to run:
    Not run directly. `from config.settings import settings`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv(path: Path) -> None:
    """Copy KEY=VALUE lines from a .env file into os.environ, without overwriting.

    Why not python-dotenv: it is one more dependency for ten lines of code.

    Args:
        path: Location of the .env file. Missing files are ignored.
    """
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv(REPO_ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    """Return environment variable `name`, or `default` if unset or empty."""
    return os.environ.get(name) or default


def _env_float(name: str, default: float) -> float:
    """Return environment variable `name` as a float."""
    return float(_env(name, str(default)))


def _env_int(name: str, default: int) -> int:
    """Return environment variable `name` as an int."""
    return int(_env(name, str(default)))


@dataclass(frozen=True)
class Settings:
    """Every tunable value in the project. Field comments say which brief section uses it."""

    # --- AWS and storage -------------------------------------------------
    aws_region: str = _env("AWS_REGION", "us-east-1")  # Sandbox is us-east-1 only
    s3_bucket: str = _env("S3_BUCKET")
    # "s3" on AWS. "local" writes the same keys under local_dir, for Codespaces/laptops.
    storage_mode: str = _env("STORAGE_MODE", "local")
    local_dir: Path = Path(_env("LOCAL_DATA_DIR", str(REPO_ROOT / "local_data")))
    # Scratch space for the batch job. On AWS this is the batch server's EBS data
    # volume (mounted at /data), so large intermediate files never touch the root disk.
    work_dir: Path = Path(_env("WORK_DIR", str(REPO_ROOT / "local_data" / "work")))
    raw_prefix: str = "raw/"
    processed_prefix: str = "processed/"
    analyses_prefix: str = "analyses/"  # Feature 3: saved analyses as Markdown

    # --- Database --------------------------------------------------------
    db_host: str = _env("DB_HOST", "localhost")
    db_port: int = _env_int("DB_PORT", 5432)
    db_name: str = _env("DB_NAME", "tradeshift")
    db_user: str = _env("DB_USER", "tradeshift")
    db_password: str = _env("DB_PASSWORD")

    # --- Data sources ------------------------------------------------------
    census_api_key: str = _env("CENSUS_API_KEY")
    census_url: str = "https://api.census.gov/data/timeseries/intltrade/imports/hs"
    comtrade_api_key: str = _env("COMTRADE_API_KEY")
    comtrade_url: str = "https://comtradeapi.un.org/data/v1/get/C/M/HS"
    # Free Comtrade key: 500 calls a day. Stop a little early to leave headroom.
    comtrade_daily_limit: int = _env_int("COMTRADE_DAILY_LIMIT", 450)
    # 2015 so the July 2016 washer anti-dumping event has a full 12-month before window.
    start_month: str = _env("START_MONTH", "2015-01")
    # Leave empty to download up to the latest month the API has published.
    end_month: str = _env("END_MONTH")
    # Second importer, through Comtrade (Features: "by importer"). 392 = Japan.
    second_importer_iso2: str = _env("SECOND_IMPORTER", "JP")
    # Census has no HS6 quantities, so US net weights come from Comtrade, but only for
    # the months the event windows use (saves most of the daily Comtrade quota).
    qty_start_month: str = _env("QTY_START_MONTH", "2017-01")
    qty_end_month: str = _env("QTY_END_MONTH", "2020-12")
    singapore_code: str = "702"
    usa_comtrade_code: str = "842"

    # --- Data cleaning -----------------------------------------------------
    # Keep the top N suppliers per importer and product; the rest become "ROW".
    # Why: keeps RDS on db.t3.micro small, and tiny suppliers never move shares by 3 points.
    top_suppliers: int = _env_int("TOP_SUPPLIERS", 15)
    # HS revision dates (HS2017, HS2022). Codes that start or stop at these dates are flagged.
    hs_revision_dates: tuple[str, ...] = ("2017-01", "2022-01")

    # --- Diversion detector (Features, "Diversion detector") ----------------
    window_months: int = _env_int("WINDOW_MONTHS", 12)  # 12 months before vs after
    lag_months: int = _env_int("LAG_MONTHS", 2)  # skip goods already in transit
    min_drop_pp: float = _env_float("MIN_DROP_PP", 5.0)  # tariffed supplier loses >= 5 points
    min_gain_pp: float = _env_float("MIN_GAIN_PP", 3.0)  # another supplier gains >= 3 points
    min_annual_value_usd: float = _env_float("MIN_ANNUAL_VALUE_USD", 10_000_000)  # filter noisy lines
    top_movers: int = _env_int("TOP_MOVERS", 20)

    # --- Singapore lens (Features, "Singapore lens") -------------------------
    sg_min_growth_pct: float = _env_float("SG_MIN_GROWTH_PCT", 25.0)  # re-exports up at least 25%
    sg_min_value_usd: float = _env_float("SG_MIN_VALUE_USD", 1_000_000)  # after-window re-exports floor

    # --- Web app -----------------------------------------------------------
    app_port: int = _env_int("APP_PORT", 8000)
    # Feature 5 target: metadata search under 2 seconds.
    search_limit: int = _env_int("SEARCH_LIMIT", 200)

    # --- Snapshot (survives the Sandbox wiping everything each session) ------
    snapshot_url: str = _env("SNAPSHOT_URL")

    # --- Display rules (Feature 1) --------------------------------------
    eu_label: str = "EU"
    country_file: Path = field(default=REPO_ROOT / "data" / "countries.csv")
    events_file: Path = field(default=REPO_ROOT / "data" / "tariff_events.csv")
    event_products_file: Path = field(default=REPO_ROOT / "data" / "tariff_event_products.csv")

    @property
    def last_month(self) -> str:
        """Latest month to request, as YYYY-MM. Defaults to two months ago (publication lag)."""
        if self.end_month:
            return self.end_month
        today = date.today()
        month_index = today.year * 12 + today.month - 1 - 2
        return f"{month_index // 12}-{month_index % 12 + 1:02d}"


settings = Settings()
