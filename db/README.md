# db/

| File | What it does |
|---|---|
| `schema.sql` | Every table, `CREATE TABLE IF NOT EXISTS`, so it is safe to run at every start |
| `indexes.sql` | Indexes beyond primary keys; the metadata indexes keep Feature 5 under 2 seconds |

There are two kinds of table:

- **Pipeline tables** (trade_monthly, hhi_monthly, event_shares, event_products, signals, did_results, singapore_*, products, countries, tariff_*): rebuilt by `batch/load_db.py` on every run.
- **App tables** (`analyses`, `notes`): user work, never truncated. Their metadata columns (hs6, importer, supplier, event_id, created_at) are indexed for search.

Both the batch server and every web server apply the schema at start, so it doesn't matter which one starts first.
