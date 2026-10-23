# app/

The Flask web app that the Auto Scaling Group runs behind the load balancer. It is
stateless: data is in RDS, saved analyses are in S3, so any server can answer any request.

| File | What it does |
|---|---|
| `app.py` | Entry point: creates the app, registers views, home page, `/health` |
| `db.py` | Every SQL query the pages run, as named functions |
| `storage.py` | Saves and reopens analyses as Markdown in S3 (Feature 3) |
| `backup.py` | Export / Import of every analysis and note as one zip (the Sandbox deletes everything each session) |
| `formatting.py` | Display rules: US$ millions, %, points, HHI, months (Feature 1) |
| `views/` | One file per page, see `views/README.md` |
| `templates/` | Jinja HTML templates; `_analysis.html` renders every page's results |
| `static/` | `app.css`, `app.js`, and `vendor/chart.umd.min.js` (Chart.js 4.5.1, MIT, served locally so the demo makes no external calls) |

Run locally: `flask --app app.app run --port 8000`. On EC2: gunicorn via `infra/scripts/web_start.sh`.
