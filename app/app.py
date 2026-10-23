"""TradeShift web app: entry point, navigation, home page and health check.

What it does:
    Creates the Flask app, registers every view, adds the number-formatting
    filters (Feature 1) and serves:
      /        home page: what TradeShift does, headline results, the validation table
      /health  JSON health check used by the load balancer; it also reports which
               instance and Availability Zone answered (load-balancing test)
    Every web server is stateless: data lives in RDS and S3, so the Auto Scaling
    Group can add or remove servers at any time.

Inputs:
    Environment settings (config/settings.py).

Outputs:
    HTTP responses.

How to run:
    Development:  flask --app app.app run --port 8000
    Production:   gunicorn -w 2 -b 0.0.0.0:8000 app.app:app   (see infra user data)
"""

from __future__ import annotations

import logging
import time

from flask import Flask, jsonify, render_template, request

from app import db
from app.formatting import FILTERS
from app.views import common, compare, concentration, detector, explorer, movers, singapore
from config.database import apply_schema
from config.logging_config import setup_logging
from config.settings import settings

log = logging.getLogger("app")

# Every page: (view module, endpoint for the menu, menu label), in menu order.
PAGES = [
    (explorer, "explorer.page", "Explorer"),
    (detector, "detector.page", "Detector"),
    (concentration, "concentration.page", "Concentration"),
    (movers, "movers.page", "Top movers"),
    (singapore, "singapore.page", "Singapore lens"),
    (compare, "compare.page", "Compare"),
]
NAV = [(endpoint, label) for _, endpoint, label in PAGES]


def ensure_schema(attempts: int = 5) -> None:
    """Create missing tables at start, retrying while RDS is still starting up.

    Why here: the analyses and notes tables must exist even before the batch job
    has loaded any trade data, so users can save work from the first minute.
    """
    for attempt in range(1, attempts + 1):
        try:
            apply_schema()
            return
        except Exception as exc:  # RDS may not accept connections yet
            log.warning("Schema setup attempt %d failed: %s", attempt, exc)
            time.sleep(5 * attempt)
    log.error("Could not reach the database; pages will show an error until it is up")


def create_app() -> Flask:
    """Build and configure the Flask application."""
    setup_logging()
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024
    app.jinja_env.filters.update(FILTERS)
    for module, _, _ in PAGES:
        app.register_blueprint(module.bp)
    app.teardown_appcontext(db.close)

    @app.context_processor
    def shared() -> dict:
        """Values every template can use: navigation, instance identity, current path."""
        return {
            "nav": NAV,
            "identity": common.instance_identity(),
            "path": request.path,
            "analysis_json": common.analysis_json,
            "f": common.filters(),
        }

    @app.route("/health")
    def health():
        """Health check for the load balancer.

        Returns 200 whenever this server can answer. The database status is reported
        but does not fail the check: if RDS blipped, replacing every web server
        would not help.
        """
        try:
            db.one("SELECT 1 AS ok")
            database = "ok"
        except Exception as exc:
            database = f"error: {type(exc).__name__}"
        return jsonify({"status": "ok", "database": database, **common.instance_identity()})

    @app.route("/")
    def home():
        """Home page with headline numbers, the validation table and links to every feature."""
        status = db.data_status()
        top = db.signals(limit=5)
        names = db.countries()
        if not top.empty:
            top["pair"] = [f"{names.get(a, a)} → {names.get(b, b)}" for a, b in zip(top["loser"], top["gainer"])]
        did = db.did_results()
        events = db.events()
        return render_template(
            "home.html", status=status, top=common.records(top), did=did, events=events, defaults=settings
        )

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404, message="That page or item does not exist."), 404

    @app.errorhandler(500)
    def server_error(e):
        log.exception("Server error: %s", e)
        return (
            render_template(
                "error.html",
                code=500,
                message="Something went wrong. If the data is still loading, try again in a minute.",
            ),
            500,
        )

    ensure_schema()
    return app


app = create_app()
