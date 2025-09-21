import os
import sqlite3
from datetime import datetime
from typing import Dict, Tuple

from flask import (
    Flask,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

STATUS_CHOICES: Tuple[Tuple[str, str], ...] = (
    ("registered", "Angemeldet"),
    ("quality_check", "Wareneingangsprüfung"),
    ("accepted", "Freigegeben"),
    ("rework", "Nacharbeit"),
    ("blocked", "Gesperrt"),
)

STATUS_CLASSES: Dict[str, str] = {
    "registered": "status-registered",
    "quality_check": "status-quality",
    "accepted": "status-accepted",
    "rework": "status-rework",
    "blocked": "status-blocked",
}


def create_app(test_config: Dict | None = None) -> Flask:
    """Application factory for the goods receipt app."""
    app = Flask(
        __name__,
        instance_relative_config=False,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "static"),
    )

    default_db = os.path.join(app.root_path, "waren_eingang.sqlite")
    app.config.from_mapping(
        SECRET_KEY="dev",
        DATABASE=default_db,
        COMPANY_NAME="Maschinenbau GmbH",
    )

    if test_config is not None:
        app.config.update(test_config)

    os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)

    @app.teardown_appcontext
    def close_db(exception):  # type: ignore[override]
        db = g.pop("db", None)
        if db is not None:
            db.close()

    with app.app_context():
        init_db()

    register_routes(app)
    return app


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE"], detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row
    return g.db


def init_db() -> None:
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier TEXT NOT NULL,
            delivery_note TEXT NOT NULL,
            purchase_order TEXT NOT NULL,
            part_number TEXT NOT NULL,
            part_description TEXT,
            quantity_expected INTEGER,
            quantity_received INTEGER,
            unit TEXT DEFAULT 'Stk',
            inspection_required INTEGER DEFAULT 1,
            certificate_received INTEGER DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'registered',
            priority TEXT DEFAULT 'normal',
            inspector TEXT,
            storage_location TEXT,
            comments TEXT,
            next_action TEXT,
            created_at TEXT NOT NULL,
            inspected_at TEXT
        );
        """
    )
    db.commit()


def register_routes(app: Flask) -> None:
    @app.context_processor
    def inject_globals():
        return {
            "status_labels": dict(STATUS_CHOICES),
            "status_classes": STATUS_CLASSES,
            "company_name": app.config.get("COMPANY_NAME", ""),
        }

    def _status_filters() -> Dict[str, int]:
        db = get_db()
        counts: Dict[str, int] = {code: 0 for code, _ in STATUS_CHOICES}
        rows = db.execute(
            "SELECT status, COUNT(*) as count FROM deliveries GROUP BY status"
        ).fetchall()
        for row in rows:
            counts[row["status"]] = row["count"]
        return counts

    @app.route("/")
    def index():
        db = get_db()
        status_filter = request.args.get("status")
        valid_status = {code for code, _ in STATUS_CHOICES}
        if status_filter and status_filter in valid_status:
            deliveries = db.execute(
                "SELECT * FROM deliveries WHERE status = ? ORDER BY created_at DESC",
                (status_filter,),
            ).fetchall()
        else:
            deliveries = db.execute(
                "SELECT * FROM deliveries ORDER BY created_at DESC"
            ).fetchall()
            status_filter = ""

        stats = _status_filters()
        total_count = sum(stats.values())
        return render_template(
            "index.html",
            deliveries=deliveries,
            stats=stats,
            active_status=status_filter,
            total_count=total_count,
        )

    @app.route("/deliveries/new", methods=("GET", "POST"))
    def create_delivery():
        if request.method == "POST":
            form = request.form
            required_fields = [
                ("supplier", "Lieferant"),
                ("delivery_note", "Lieferscheinnummer"),
                ("purchase_order", "Bestellnummer"),
                ("part_number", "Artikelnummer"),
            ]
            missing = [label for field, label in required_fields if not form.get(field)]
            if missing:
                flash(
                    "Bitte folgende Pflichtfelder ausfüllen: " + ", ".join(missing),
                    "error",
                )
                return render_template("new_delivery.html", form_data=form)

            quantity_expected = _parse_int(form.get("quantity_expected"))
            quantity_received = _parse_int(form.get("quantity_received"))

            db = get_db()
            db.execute(
                """
                INSERT INTO deliveries (
                    supplier, delivery_note, purchase_order, part_number,
                    part_description, quantity_expected, quantity_received,
                    unit, inspection_required, certificate_received, status,
                    priority, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    form.get("supplier", "").strip(),
                    form.get("delivery_note", "").strip(),
                    form.get("purchase_order", "").strip(),
                    form.get("part_number", "").strip(),
                    form.get("part_description", "").strip(),
                    quantity_expected,
                    quantity_received,
                    form.get("unit", "Stk").strip() or "Stk",
                    1 if form.get("inspection_required") else 0,
                    1 if form.get("certificate_received") else 0,
                    form.get("status", "registered"),
                    form.get("priority", "normal"),
                    datetime.utcnow().isoformat(timespec="seconds"),
                ),
            )
            db.commit()
            flash("Wareneingang erfolgreich erfasst.", "success")
            return redirect(url_for("index"))

        return render_template("new_delivery.html", form_data={})

    @app.route("/deliveries/<int:delivery_id>/inspect", methods=("GET", "POST"))
    def update_delivery(delivery_id: int):
        db = get_db()
        delivery = db.execute(
            "SELECT * FROM deliveries WHERE id = ?", (delivery_id,)
        ).fetchone()
        if delivery is None:
            abort(404)

        if request.method == "POST":
            form = request.form
            new_status = form.get("status", delivery["status"])
            quantity_received = _parse_int(form.get("quantity_received"))
            inspected_at = (
                datetime.utcnow().isoformat(timespec="seconds")
                if new_status != "registered"
                else delivery["inspected_at"]
            )

            db.execute(
                """
                UPDATE deliveries
                   SET status = ?,
                       inspector = ?,
                       quantity_received = ?,
                       storage_location = ?,
                       comments = ?,
                       next_action = ?,
                       certificate_received = ?,
                       priority = ?,
                       inspected_at = ?
                 WHERE id = ?
                """,
                (
                    new_status,
                    form.get("inspector", "").strip() or None,
                    quantity_received,
                    form.get("storage_location", "").strip() or None,
                    form.get("comments", "").strip() or None,
                    form.get("next_action", "").strip() or None,
                    1 if form.get("certificate_received") else 0,
                    form.get("priority", delivery["priority"] or "normal"),
                    inspected_at,
                    delivery_id,
                ),
            )
            db.commit()
            flash("Wareneingang aktualisiert.", "success")
            return redirect(url_for("index"))

        return render_template("inspect_delivery.html", delivery=delivery)


def _parse_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = ["create_app", "init_db", "get_db", "STATUS_CHOICES", "STATUS_CLASSES"]
