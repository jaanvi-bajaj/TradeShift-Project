# app/views/

One page per file. Each builds an **analysis** (summary sentences, charts, tables,
sources) with `common.analysis()`. That one object is what the page shows and what
"Save analysis" stores, so saved analyses reopen identically.

| File | Route | Feature |
|---|---|---|
| `common.py` | – | Shared filters, chart specs, instance ID for the footer |
| `explorer.py` | `/explorer`, `/api/products` | Corridor explorer (extra) |
| `detector.py` | `/detector`, `/source/<event>/<hs6>` | Diversion detector with sliders (extra); source pages (Feature 1) |
| `concentration.py` | `/concentration` | HHI before and after (extra) |
| `movers.py` | `/movers` | Top movers (extra) |
| `singapore.py` | `/singapore` | Singapore lens (extra) |
| `compare.py` | `/compare` | Feature 2, comparison |
| `history.py` | `/history`, `/history/save`, `/history/<id>`, `/history/export`, `/history/import` | Feature 3, saved analyses; export/import across Sandbox sessions |
| `notes.py` | `/notes` | Feature 4, notes |
| `search.py` | `/search` | Feature 5, metadata search |
