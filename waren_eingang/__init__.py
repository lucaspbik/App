from __future__ import annotations

import os
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import parse_qs

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


class HTTPError(Exception):
    """Lightweight HTTP-style exception used by the mini framework."""

    def __init__(self, status: int, message: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def abort(status: int, message: str = "") -> None:
    raise HTTPError(status, message or "Aborted")


class Response:
    """Simple response object mimicking Flask's interface for tests."""

    def __init__(
        self,
        body: str | bytes = "",
        status: int = 200,
        content_type: str = "text/plain; charset=utf-8",
        headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        if isinstance(body, str):
            body_bytes = body.encode("utf-8")
        else:
            body_bytes = bytes(body)
        self.data = body_bytes
        self.status_code = status
        self.content_type = content_type
        self.headers: Dict[str, str] = dict(headers or {})


class Request:
    def __init__(
        self,
        method: str,
        path: str,
        form: Optional[Mapping[str, Any]] = None,
        query: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.method = method.upper()
        self.path = path
        self.form: Dict[str, Any] = {k: v for k, v in (form or {}).items()}
        self.args: Dict[str, Any] = {k: v for k, v in (query or {}).items()}


class _AppContext:
    def __init__(self, app: "GoodsReceiptApp") -> None:
        self.app = app
        self.g: Dict[str, Any] = {}


_app_ctx_stack: List[_AppContext] = []
_request_stack: List[Request] = []


def _get_current_app_ctx() -> _AppContext:
    if not _app_ctx_stack:
        raise RuntimeError("Application context not active")
    return _app_ctx_stack[-1]


class _CurrentAppProxy:
    def __getattr__(self, item: str) -> Any:
        return getattr(_get_current_app_ctx().app, item)


current_app = _CurrentAppProxy()


class _GProxy:
    def _storage(self) -> Dict[str, Any]:
        return _get_current_app_ctx().g

    def __contains__(self, key: str) -> bool:
        return key in self._storage()

    def __getitem__(self, key: str) -> Any:
        return self._storage()[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._storage()[key] = value

    def pop(self, key: str, default: Any = None) -> Any:
        return self._storage().pop(key, default)

    def get(self, key: str, default: Any = None) -> Any:
        return self._storage().get(key, default)


g = _GProxy()


class _RequestProxy:
    def __getattr__(self, item: str) -> Any:
        if not _request_stack:
            raise RuntimeError("Request context not active")
        return getattr(_request_stack[-1], item)


request = _RequestProxy()


@dataclass
class Route:
    rule: str
    methods: Tuple[str, ...]
    pattern: re.Pattern[str]
    converters: Dict[str, Callable[[str], Any]]
    handler: Callable[..., Any]


class GoodsReceiptApp:
    def __init__(self) -> None:
        self.config: Dict[str, Any] = {}
        self.root_path = str(Path(__file__).resolve().parent)
        self.static_folder = os.path.join(self.root_path, "static")
        self.template_folder = os.path.join(self.root_path, "templates")
        self._routes: List[Route] = []
        self._teardown_callbacks: List[Callable[[BaseException | None], None]] = []

    def route(
        self, rule: str, methods: Iterable[str] | None = None
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        allowed = tuple(method.upper() for method in (methods or ("GET",)))

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.add_url_rule(rule, func, allowed)
            return func

        return decorator

    def add_url_rule(
        self, rule: str, handler: Callable[..., Any], methods: Tuple[str, ...]
    ) -> None:
        pattern, converters = _compile_route(rule)
        self._routes.append(Route(rule, methods, pattern, converters, handler))

    def teardown_appcontext(
        self, func: Callable[[BaseException | None], None]
    ) -> Callable[[BaseException | None], None]:
        self._teardown_callbacks.append(func)
        return func

    @contextmanager
    def app_context(self) -> Iterable["GoodsReceiptApp"]:
        ctx = _AppContext(self)
        _app_ctx_stack.append(ctx)
        exc: BaseException | None = None
        try:
            yield self
        except BaseException as err:
            exc = err
            raise
        finally:
            for callback in self._teardown_callbacks:
                callback(exc)
            db = ctx.g.pop("db", None)
            if db is not None:
                db.close()
            _app_ctx_stack.pop()

    def _dispatch_request(
        self,
        method: str,
        path: str,
        form_data: Optional[Mapping[str, Any]] = None,
        query_data: Optional[Mapping[str, Any]] = None,
    ) -> Response:
        method = method.upper()
        try:
            route, params = self._match_route(method, path)
        except HTTPError as err:
            return Response(err.message or "", status=err.status)

        req = Request(method, path, form=form_data, query=query_data)
        _request_stack.append(req)
        try:
            with self.app_context():
                try:
                    result = route.handler(**params)
                except HTTPError as err:
                    response = Response(err.message or "", status=err.status)
                else:
                    response = _make_response(result)
        finally:
            _request_stack.pop()
        return response

    def _match_route(self, method: str, path: str) -> Tuple[Route, Dict[str, Any]]:
        allowed_methods: set[str] = set()
        for route in self._routes:
            match = route.pattern.fullmatch(path)
            if not match:
                continue
            if method in route.methods:
                params = {
                    name: route.converters.get(name, lambda value: value)(value)
                    for name, value in match.groupdict().items()
                }
                return route, params
            allowed_methods.update(route.methods)
        if allowed_methods:
            raise HTTPError(405, "Methode nicht erlaubt")
        raise HTTPError(404, "Nicht gefunden")

    def test_client(self) -> "_TestClient":
        return _TestClient(self)

    def run(self, host: str = "127.0.0.1", port: int = 8000, debug: bool = False) -> None:
        from wsgiref.simple_server import make_server

        def application(environ, start_response):
            path = environ.get("PATH_INFO") or "/"
            method = environ.get("REQUEST_METHOD", "GET")
            query_string = environ.get("QUERY_STRING", "")
            query_data = {
                key: values[-1]
                for key, values in parse_qs(query_string, keep_blank_values=True).items()
            }
            form_data: Dict[str, Any] = {}
            if method.upper() == "POST":
                try:
                    length = int(environ.get("CONTENT_LENGTH") or 0)
                except (TypeError, ValueError):
                    length = 0
                body_bytes = environ["wsgi.input"].read(length)
                form_data = {
                    key: values[-1]
                    for key, values in parse_qs(
                        body_bytes.decode("utf-8"), keep_blank_values=True
                    ).items()
                }
            response = self._dispatch_request(
                method, path, form_data=form_data, query_data=query_data
            )
            status_line = _status_line(response.status_code)
            headers = [("Content-Type", response.content_type)]
            for key, value in response.headers.items():
                headers.append((key, value))
            headers.append(("Content-Length", str(len(response.data))))
            start_response(status_line, headers)
            return [response.data]

        with make_server(host, port, application) as server:
            if debug:
                print(f"* Running on http://{host}:{port}")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                if debug:
                    print("* Server stopped")


class _TestClient:
    def __init__(self, app: GoodsReceiptApp) -> None:
        self.app = app

    def get(
        self, path: str, query_string: Optional[Mapping[str, Any]] = None
    ) -> Response:
        clean_path, query_from_path = _split_path_and_query(path)
        query_data: Dict[str, Any] = {**query_from_path}
        if query_string:
            query_data.update({k: str(v) for k, v in query_string.items()})
        return self.app._dispatch_request("GET", clean_path, query_data=query_data)

    def post(
        self,
        path: str,
        data: Optional[Mapping[str, Any]] = None,
        follow_redirects: bool | None = None,
    ) -> Response:
        del follow_redirects
        clean_path, _ = _split_path_and_query(path)
        form_data = {k: str(v) for k, v in (data or {}).items()}
        return self.app._dispatch_request("POST", clean_path, form_data=form_data)


def _split_path_and_query(path: str) -> Tuple[str, Dict[str, Any]]:
    if "?" not in path:
        return path, {}
    pure_path, query_string = path.split("?", 1)
    query_data = {
        key: values[-1]
        for key, values in parse_qs(query_string, keep_blank_values=True).items()
    }
    return pure_path, query_data


def _compile_route(rule: str) -> Tuple[re.Pattern[str], Dict[str, Callable[[str], Any]]]:
    pattern = "^"
    converters: Dict[str, Callable[[str], Any]] = {}
    idx = 0
    while idx < len(rule):
        char = rule[idx]
        if char == "<":
            end_idx = rule.index(">", idx)
            segment = rule[idx + 1 : end_idx]
            if ":" in segment:
                conv, name = segment.split(":", 1)
            else:
                conv, name = "str", segment
            if conv == "int":
                converters[name] = int
                pattern += rf"(?P<{name}>\d+)"
            else:
                converters[name] = lambda value: value
                pattern += rf"(?P<{name}>[^/]+)"
            idx = end_idx + 1
            continue
        if char in ".^$+?{}[]|()":
            pattern += "\\" + char
        else:
            pattern += char
        idx += 1
    pattern += "$"
    return re.compile(pattern), converters


def _status_line(status: int) -> str:
    mapping = {
        200: "200 OK",
        201: "201 CREATED",
        204: "204 NO CONTENT",
        400: "400 BAD REQUEST",
        404: "404 NOT FOUND",
        405: "405 METHOD NOT ALLOWED",
    }
    return mapping.get(status, f"{status} OK")


def _make_response(value: Any) -> Response:
    if isinstance(value, Response):
        return value
    if isinstance(value, tuple):
        if len(value) == 2:
            body, status = value
            return Response(body=body, status=int(status))
        if len(value) == 3:
            body, status, headers = value
            return Response(body=body, status=int(status), headers=headers)
    if isinstance(value, (bytes, bytearray)):
        return Response(body=bytes(value))
    return Response(body=str(value))


def create_app(test_config: Optional[Mapping[str, Any]] = None) -> GoodsReceiptApp:
    app = GoodsReceiptApp()

    default_db = os.path.join(app.root_path, "waren_eingang.sqlite")
    app.config.update(
        {
            "SECRET_KEY": "dev",
            "DATABASE": default_db,
            "COMPANY_NAME": "Maschinenbau GmbH",
            "TESTING": False,
        }
    )
    if test_config is not None:
        app.config.update(test_config)

    db_path = Path(app.config["DATABASE"])
    if db_path.parent and not db_path.parent.exists():
        db_path.parent.mkdir(parents=True, exist_ok=True)

    @app.teardown_appcontext
    def close_db(exc: BaseException | None) -> None:
        del exc
        db = g.pop("db", None)
        if db is not None:
            db.close()

    register_routes(app)

    with app.app_context():
        init_db()

    return app


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        connection = sqlite3.connect(
            current_app.config["DATABASE"], detect_types=sqlite3.PARSE_DECLTYPES
        )
        connection.row_factory = sqlite3.Row
        g["db"] = connection
    return g["db"]


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


def register_routes(app: GoodsReceiptApp) -> None:
    def _status_filters() -> Dict[str, int]:
        db = get_db()
        counts: Dict[str, int] = {code: 0 for code, _ in STATUS_CHOICES}
        rows = db.execute(
            "SELECT status, COUNT(*) AS count FROM deliveries GROUP BY status"
        ).fetchall()
        for row in rows:
            counts[row["status"]] = row["count"]
        return counts

    @app.route("/", methods=("GET",))
    def index() -> Response:
        db = get_db()
        status_filter = request.args.get("status")
        valid_status = {code for code, _ in STATUS_CHOICES}
        query = "SELECT * FROM deliveries"
        params: Tuple[Any, ...] = ()
        if status_filter and status_filter in valid_status:
            query += " WHERE status = ?"
            params = (status_filter,)
        query += " ORDER BY created_at DESC"
        deliveries = db.execute(query, params).fetchall()

        stats = _status_filters()
        total = sum(stats.values())
        lines = [
            f"Wareneingang – {current_app.config.get('COMPANY_NAME', '')}",
            f"Gesamt: {total}",
        ]
        for code, label in STATUS_CHOICES:
            lines.append(f"{label}: {stats[code]}")
        if deliveries:
            lines.append("")
            for row in deliveries:
                desc = row["part_description"] or ""
                lines.append(
                    f"#{row['id']} {row['supplier']} – {row['part_number']} {desc} [{row['status']}]"
                )
        else:
            lines.append("")
            lines.append("Keine Wareneingänge erfasst.")
        return Response(" | ".join(lines))

    @app.route("/deliveries/new", methods=("GET", "POST"))
    def create_delivery() -> Response:
        if request.method == "GET":
            return Response("Bitte senden Sie ein POST-Formular, um einen Wareneingang anzulegen.")

        form = request.form
        required_fields = (
            ("supplier", "Lieferant"),
            ("delivery_note", "Lieferscheinnummer"),
            ("purchase_order", "Bestellnummer"),
            ("part_number", "Artikelnummer"),
        )
        missing = [
            label
            for field, label in required_fields
            if not (form.get(field) or "").strip()
        ]
        if missing:
            message = "Bitte folgende Pflichtfelder ausfüllen: " + ", ".join(missing)
            return Response(message, status=400)

        supplier = (form.get("supplier") or "").strip()
        delivery_note = (form.get("delivery_note") or "").strip()
        purchase_order = (form.get("purchase_order") or "").strip()
        part_number = (form.get("part_number") or "").strip()
        part_description = (form.get("part_description") or "").strip() or None
        unit = (form.get("unit") or "Stk").strip() or "Stk"
        status_value = (form.get("status") or "registered").strip() or "registered"
        priority = (form.get("priority") or "normal").strip() or "normal"

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
                supplier,
                delivery_note,
                purchase_order,
                part_number,
                part_description,
                quantity_expected,
                quantity_received,
                unit,
                1 if form.get("inspection_required") else 0,
                1 if form.get("certificate_received") else 0,
                status_value,
                priority,
                datetime.utcnow().isoformat(timespec="seconds"),
            ),
        )
        db.commit()
        return Response("Wareneingang erfolgreich erfasst")

    @app.route("/deliveries/<int:delivery_id>/inspect", methods=("GET", "POST"))
    def update_delivery(delivery_id: int) -> Response:
        db = get_db()
        delivery = db.execute(
            "SELECT * FROM deliveries WHERE id = ?", (delivery_id,)
        ).fetchone()
        if delivery is None:
            abort(404, "Wareneingang nicht gefunden")

        if request.method == "POST":
            form = request.form
            new_status = (form.get("status") or delivery["status"]).strip() or delivery["status"]
            quantity_received = _parse_int(form.get("quantity_received"))
            inspected_at = (
                datetime.utcnow().isoformat(timespec="seconds")
                if new_status != "registered"
                else delivery["inspected_at"]
            )
            inspector = (form.get("inspector") or "").strip() or None
            storage_location = (form.get("storage_location") or "").strip() or None
            comments = (form.get("comments") or "").strip() or None
            next_action = (form.get("next_action") or "").strip() or None
            priority = (form.get("priority") or delivery["priority"] or "normal").strip() or "normal"

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
                    inspector,
                    quantity_received,
                    storage_location,
                    comments,
                    next_action,
                    1 if form.get("certificate_received") else 0,
                    priority,
                    inspected_at,
                    delivery_id,
                ),
            )
            db.commit()
            return Response("Wareneingang aktualisiert")

        lines = [
            f"Wareneingang #{delivery['id']} – {delivery['supplier']}",
            f"Status: {delivery['status']}",
        ]
        return Response(" | ".join(lines))


def _parse_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "create_app",
    "init_db",
    "get_db",
    "STATUS_CHOICES",
    "STATUS_CLASSES",
    "GoodsReceiptApp",
    "Response",
]
