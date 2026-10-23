# tests/

Run everything with `pytest` from the repo root.

| File | What it checks |
|---|---|
| `test_metrics.py` | Shares sum to 100% per product-month; HHI matches a hand-worked example (60/30/10 gives 4,600); growth, CAGR, windows, tariffed-supplier sets |
| `test_detector.py` | Detector rules and thresholds, gainer must be untariffed, confidence labels, trade-destruction label; DiD recovers a planted −10 point effect |
| `test_formatting.py` | No scientific notation; US$ millions, %, points, HHI, month labels |
| `test_storage.py` | A saved analysis reopens identically; local storage round trip |
| `test_pipeline_smoke.py` | Synthetic raw data through every step; with `TRADESHIFT_TEST_DB=1` also loads PostgreSQL twice (no duplicates) and opens every page |
| `fake_data.py` | The synthetic data (invented numbers, used only by the smoke test) |

The database part of the smoke test runs only against a disposable local PostgreSQL:

```bash
TRADESHIFT_TEST_DB=1 DB_HOST=127.0.0.1 DB_PORT=5432 DB_USER=tradeshift pytest tests/test_pipeline_smoke.py
```
