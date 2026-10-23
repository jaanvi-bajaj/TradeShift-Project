# batch/

The data pipeline. It runs on the batch EC2 server (or locally). One job per file;
`run_pipeline.py` runs them in order.

| Step | File | Reads | Writes |
|---|---|---|---|
| 1 | `download_census.py` | Census API | `raw/census/YYYY-MM.json.gz` |
| 2 | `download_comtrade.py` | Comtrade API (quota-aware, resumable): Singapore's exports to the US, US net weights for 2017–2020, Japan's imports | `raw/comtrade/...`, call log |
| 2b | `download_singstat.py` | SingStat: official re-exports and domestic exports to the US, S$/US$ rate | `raw/singstat/*.json.gz` |
| 3 | `clean.py` | raw files | `processed/trade/<importer>/<hs2>.csv.gz`, `products`, `singapore`, `singapore_official`, `totals_check` |
| 4 | `metrics.py` | processed trade | `processed/hhi/...`, `event_shares`, `event_products` |
| 5 | `detector.py` | event tables | `processed/signals.csv.gz` |
| 6 | `did_check.py` | processed trade | `processed/did_results.csv.gz` |
| 7 | `singapore.py` | Singapore flows, event shares | `processed/singapore_lens.csv.gz` |
| 8 | `explain.py` | signals | `processed/signals_explained.csv.gz` |
| 9 | `load_db.py` | all processed tables | RDS (truncate + COPY per table) |
| 10 | `ebs_snapshot.py` | instance metadata | EBS snapshot of the data volume |

Helpers: `storage_io.py` (S3 or local folder, same keys) and `snapshot.py` (export and
restore the processed data as one file).

```bash
python -m batch.run_pipeline                     # full run; finished steps are skipped
python -m batch.run_pipeline --from metrics      # redo from one step
python -m batch.run_pipeline --force             # redo everything
python -m batch.run_pipeline --mode snapshot --snapshot-url <url>   # what a new stack runs
python -m batch.snapshot export                  # pack processed/ for a GitHub release
```

**Re-runnable:** a step writes `processed/_steps/<step>.json.gz` when it succeeds, so a
failed run resumes at the failed step. New downloads make every later step re-run.
`load_db` replaces table contents, so running it twice never duplicates rows.
