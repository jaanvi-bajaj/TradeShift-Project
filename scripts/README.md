# scripts/

Developer tools. None of them run during deployment or the demo.

| File | What it does |
|---|---|
| `build_tariff_lines.py` | Rebuilds `data/tariff_event_products.csv` from the Federal Register notices |
| `build_reference.py` | Rebuilds `data/countries.csv` from the Census and Comtrade code lists |
| `build_wheelhouse.sh` | Builds the offline wheel bundle (Linux, Python 3.11) for the GitHub release |
| `load_test.py` | Sends load to the ALB for the auto scaling test, and reports which instances answered |
| `make_demo_content.py` | Saves a few demo analyses and notes and exports them into `processed/demo/`, so new stacks have a non-empty History |
