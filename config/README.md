# config/

Shared settings and helpers used by both the batch job and the web app.

| File | What it does |
|---|---|
| `settings.py` | Every tunable value: AWS region, bucket, database, API URLs, detector thresholds, windows, Singapore lens thresholds. Read from environment variables (locally also from `.env`), with defaults. Change a threshold here or with an environment variable, never in code. |
| `database.py` | `connect()` opens a PostgreSQL connection; `apply_schema()` runs `db/schema.sql` and `db/indexes.sql` (safe to repeat). |
| `logging_config.py` | `setup_logging()`: one log format, written to stdout so CloudWatch collects it. |
