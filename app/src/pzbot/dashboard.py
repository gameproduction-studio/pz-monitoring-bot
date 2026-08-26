"""Loopback-only HTTP dashboard for the Survivor Organizer."""

from __future__ import annotations

import ipaddress
import json
import logging
import mimetypes
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .settings import Settings

LOG = logging.getLogger("pz_monitoring_bot.dashboard")

SUPPORTED_GAME_LANGUAGES = (
    "AR", "CA", "CH", "CN", "CS", "DA", "DE", "EN", "ES", "ES_CL",
    "ES_MX", "FI", "FR", "HU", "ID", "IT", "JP", "KO", "NL", "NO",
    "PL", "PT", "PTBR", "RO", "RU", "STREW", "TH", "TR", "UA",
)
DOCUMENT_NAMES = {
    "bootstrap": "chatgpt_state.json",
    "status": "status.json",
    "current": "current_state.json",
}
SECTION_NAMES = {
    "overview", "character", "bases", "vehicles", "food",
    "resources", "changes", "calculations",
}


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _resolve_contract_path(settings: Settings, value: str) -> Path | None:
    relative = Path(value.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts:
        return None
    root = settings.live_dir.parent.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _section_document(
    settings: Settings, bootstrap: dict[str, Any], name: str
) -> Any:
    value = (bootstrap.get("sectionPaths") or {}).get(name)
    if not isinstance(value, str):
        return None
    path = _resolve_contract_path(settings, value)
    return _read_json(path) if path else None


def _game_language(bootstrap: dict[str, Any]) -> str | None:
    status = bootstrap.get("status") or {}
    mod_game = ((status.get("modStatus") or {}).get("game") or {})
    game = status.get("game") or bootstrap.get("game") or {}
    value = str(mod_game.get("language") or game.get("language") or "").upper()
    return value if value in SUPPORTED_GAME_LANGUAGES else None


def build_dashboard_payload(settings: Settings) -> dict[str, Any]:
    bootstrap = _read_json(settings.live_dir / "chatgpt_state.json", {})
    selected = settings.dashboard.language.upper()
    game_language = _game_language(bootstrap)
    if selected == "AUTO" or selected not in SUPPORTED_GAME_LANGUAGES:
        selected = game_language or "AUTO"
    sections = {
        name: _section_document(settings, bootstrap, name)
        for name in SECTION_NAMES
    }
    return {
        "schema": "pz-monitoring-bot/dashboard/v1",
        "language": {
            "selected": selected,
            "game": game_language,
            "detectedFromGame": game_language is not None,
            "mode": settings.dashboard.language.lower(),
            "available": list(SUPPORTED_GAME_LANGUAGES),
        },
        "bootstrap": bootstrap,
        "sections": sections,
    }


def build_health(settings: Settings) -> dict[str, Any]:
    bootstrap = _read_json(settings.live_dir / "chatgpt_state.json", {})
    status = bootstrap.get("status") or {}
    mod_status = status.get("modStatus") or {}
    return {
        "ok": bool(status.get("ok")),
        "parsingSuccessful": bool(status.get("parsingSuccessful")),
        "sequence": mod_status.get("sequence"),
        "lastScanAt": status.get("lastScanAt"),
        "saveId": (status.get("activeSave") or {}).get("id"),
        "contractRevision": status.get("contractRevision"),
    }


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class DashboardRequestHandler(BaseHTTPRequestHandler):
    server_version = "PZOrganizer/0.3"
    settings: Settings

    def log_message(self, fmt: str, *args: object) -> None:
        LOG.debug("%s - %s", self.address_string(), fmt % args)

    def _headers(self, content_type: str, length: int) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'",
        )
        self.end_headers()

    def _json(self, value: Any) -> None:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._headers("application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def _asset(self, relative: str) -> None:
        root = Path(__file__).with_name("web").resolve()
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type == "application/javascript":
            content_type += "; charset=utf-8"
        self._headers(content_type, len(body))
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        route = unquote(urlparse(self.path).path)
        if route == "/api/v1/health":
            self._json(build_health(self.settings))
            return
        if route == "/api/v1/dashboard":
            self._json(build_dashboard_payload(self.settings))
            return
        if route.startswith("/api/v1/document/"):
            name = route.rsplit("/", 1)[-1]
            bootstrap = _read_json(self.settings.live_dir / "chatgpt_state.json", {})
            if name in DOCUMENT_NAMES:
                self._json(_read_json(self.settings.live_dir / DOCUMENT_NAMES[name], {}))
                return
            if name in SECTION_NAMES:
                self._json(_section_document(self.settings, bootstrap, name) or {})
                return
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if route.startswith("/api/v1/page/"):
            filename = route.rsplit("/", 1)[-1]
            if not filename.endswith(".json") or any(
                token in filename for token in ("..", "/", "\\")
            ):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            page = (self.settings.live_dir / "chatgpt" / filename).resolve()
            root = (self.settings.live_dir / "chatgpt").resolve()
            try:
                page.relative_to(root)
            except ValueError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not page.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._json(_read_json(page, {}))
            return
        if route in {"/", "/index.html"}:
            self._asset("index.html")
            return
        if route.startswith("/assets/"):
            self._asset(route.removeprefix("/assets/"))
            return
        self.send_error(HTTPStatus.NOT_FOUND)


@dataclass
class DashboardHandle:
    server: ThreadingHTTPServer
    thread: threading.Thread | None

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}/"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)


def start_dashboard(
    settings: Settings,
    *,
    background: bool = True,
) -> DashboardHandle:
    if not _is_loopback(settings.dashboard.host):
        raise ValueError("Dashboard host must be loopback-only")
    handler = type(
        "ConfiguredDashboardHandler",
        (DashboardRequestHandler,),
        {"settings": settings},
    )
    server = ThreadingHTTPServer(
        (settings.dashboard.host, settings.dashboard.port),
        handler,
    )
    server.daemon_threads = True
    if not background:
        handle = DashboardHandle(server=server, thread=None)
        LOG.info("dashboard available at %s", handle.url)
        try:
            server.serve_forever(poll_interval=0.25)
        finally:
            server.server_close()
        return handle
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.25},
        name="pz-organizer-dashboard",
        daemon=True,
    )
    thread.start()
    handle = DashboardHandle(server=server, thread=thread)
    LOG.info("dashboard available at %s", handle.url)
    return handle
