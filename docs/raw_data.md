# Raw data

The raw data is the API responses exactly as they were downloaded, before any cleaning.
It is **not in this repository and not on GitHub**. It stays on the laptop that ran the
downloads, so the 500-calls-a-day Comtrade quota never has to be spent again.

## What it is

| Folder (under `local_data/raw/`) | Source | Files | Size | Covers |
|---|---|---|---|---|
| `census/` | US Census international trade API | 140 (one per month) | 611 MB | US imports by country and HS6, Jan 2015 – Aug 2026 |
| `comtrade/imports_392/` | UN Comtrade | 140 (one per month) | 166 MB | Japan's imports by partner and HS6 |
| `comtrade/imports_842/` | UN Comtrade | 48 (one per month) | 117 MB | US imports with net weights, 2017–2020 (the quantity check) |
| `comtrade/sg_X/` | UN Comtrade | 12 (one per year) | 5 MB | Singapore's exports to the US by HS6 |
| `singstat/` | SingStat Table Builder | 3 | 12 KB | Singapore's official re-exports and domestic exports to the US; S$/US$ rate |
| `comtrade/_calls/` | (our log) | 1 | 4 KB | Every Comtrade call made, for the quota |

Total: about 900 MB (gzipped JSON). The same files are also packed, ready to share, in
`dist/tradeshift-raw.json` plus `dist/tradeshift-raw.tar.gz.part00` … `part09` (10 parts under
95 MB each, with a SHA-256 for each part in the `.json` manifest).

## Why it is not published

US Census and SingStat data are open. UN Comtrade's terms restrict redistributing bulk
downloads, and this repository is public. The app only needs the **processed** data, which
is published as the `data-v1` release; that is what every new stack loads.

## How to use it

- **Rebuild the processed data** (for example after changing a threshold):
  `python -m batch.run_pipeline --from clean`. The download steps see every file is already
  there and fetch nothing.
- **Share it inside the group:** send the `dist/tradeshift-raw*` files privately (OneDrive,
  Google Drive). The receiver restores them with
  `python -m batch.snapshot restore <folder>/tradeshift-raw.json`.
- **Get it again from scratch:** `python -m batch.run_pipeline` with `CENSUS_API_KEY` and
  `COMTRADE_API_KEY` in `.env` (see `README.md`). It takes a few hours, mostly Census.
