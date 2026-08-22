"""Command-line entry point for the local Windows monitor."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .active_save import ActiveSave, activity_signature, resolve_active_save
from .character_scan import scan_character
from .git_sync import GitSync
from .instance_lock import InstanceAlreadyRunning, single_instance
from .jsonio import atomic_write_json
from .live_contract import (
    build_current_state,
    build_error_status,
    build_status,
    load_local_state,
    previous_for_save,
    save_local_state,
    update_local_state,
    utc_now,
    write_live_files,
)
from .mod_relay import relay_once
from .ownership import apply_ownership
from .pz_save_scanner import read_player_snapshot
from .safe_snapshot import safe_save_snapshot
from .savewatch import wait_stable
from .settings import Settings, load_settings
from .state_diff import compare_states, flatten_state
from .world_chunk import scan_world_chunks


LOG = logging.getLogger("pz_monitoring_bot")


def _configure_logging(settings: Settings, verbose: bool = False) -> None:
    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(settings.log_path, encoding="utf-8"),
    ]
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )


def _iso_mtime(path: Path) -> str:
    value = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc)
    return value.isoformat(timespec="seconds")


def _vehicle_coverage(db_path: Path) -> dict[str, Any]:
    if not db_path.is_file():
        return {
            "complete": True,
            "databaseRows": 0,
            "parsedVehicles": 0,
            "note": "vehicles.db is absent",
        }
    uri = "file:" + quote(db_path.resolve().as_posix()) + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=10) as connection:
        connection.execute("PRAGMA query_only=ON")
        rows = int(connection.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0])
    return {
        "complete": rows == 0,
        "databaseRows": rows,
        "parsedVehicles": 0,
        "note": (
            "No saved vehicles in this save."
            if rows == 0
            else "Vehicle BLOB parsing is not implemented yet; vehicle containers are excluded."
        ),
    }


def _build_snapshot(
    settings: Settings,
    active: ActiveSave,
    snapshot_dir: Path,
) -> dict[str, Any]:
    character = scan_character(snapshot_dir, settings.game_path)
    world = scan_world_chunks(snapshot_dir, settings.game_path)
    world["vehicles"] = []
    world["vehicleCoverage"] = _vehicle_coverage(snapshot_dir / "vehicles.db")
    apply_ownership(
        world,
        zones=settings.base_zones,
        save_id=active.save_id,
        explicitly_opened=set(settings.explicitly_opened_container_ids),
        manual_owned=set(settings.manual_owned_container_ids),
    )
    return {
        "schema": "pz-monitoring-bot/internal-snapshot/v1",
        "save": active.public_dict(),
        "worldVersion": character["worldVersion"],
        "character": character,
        "world": world,
        "baseZones": [
            dict(zone)
            for zone in settings.base_zones
            if not zone.get("save_id") or zone.get("save_id") == active.save_id
        ],
    }


def scan_once(settings: Settings, *, active: ActiveSave | None = None) -> dict[str, Any]:
    active = active or resolve_active_save(
        settings.save_root,
        override=settings.save_override,
    )
    LOG.info(
        "active save mode=%s name=%s source=%s",
        active.game_mode,
        active.folder_name,
        active.selection_source,
    )
    players_db = active.path / "players.db"
    wait_stable(
        players_db,
        polls=settings.stable_polls,
        interval=settings.stable_interval_seconds,
    )
    save_write_time = _iso_mtime(players_db)
    scan_time = utc_now()

    with safe_save_snapshot(active.path, settings.runtime_dir) as snapshot_dir:
        snapshot = _build_snapshot(settings, active, snapshot_dir)

    local_state = load_local_state(settings.state_path)
    previous = previous_for_save(local_state, active.save_id)
    events = compare_states(previous, snapshot, timestamp=scan_time)
    current_state = build_current_state(snapshot, events=events, scan_time=scan_time)
    publication_mode = (
        "automatic_direct_push_to_main"
        if settings.publish.enabled
        else "local_only"
    )
    status = build_status(
        snapshot,
        scan_time=scan_time,
        save_write_time=save_write_time,
        events=events,
        publish_state=publication_mode,
    )

    write_live_files(
        settings.live_dir,
        current_state=current_state,
        status=status,
        events=events,
    )
    update_local_state(local_state, snapshot, scan_time=scan_time)
    save_local_state(settings.state_path, local_state)

    publication_result = GitSync(settings.publish).publish_if_dirty(
        save_name=active.folder_name,
        updated_at=scan_time,
    )
    LOG.info(
        "scan ok items=%s containers=%s corpses=%s changes=%s publish=%s",
        len(flatten_state(snapshot)),
        len(snapshot["world"].get("containers") or []),
        len(snapshot["world"].get("corpses") or []),
        len(events),
        publication_result,
    )
    return {
        "save": active.public_dict(),
        "scanTime": scan_time,
        "items": len(flatten_state(snapshot)),
        "containers": len(snapshot["world"].get("containers") or []),
        "corpses": len(snapshot["world"].get("corpses") or []),
        "changes": events,
        "publication": publication_result,
        "coverage": status["coverage"],
    }


def _write_failure(settings: Settings, active: ActiveSave | None, exc: Exception) -> None:
    LOG.exception("scan failed")
    settings.live_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        settings.live_dir / "status.json",
        build_error_status(
            save=active.public_dict() if active else None,
            error=f"{type(exc).__name__}: {exc}",
        ),
    )


def monitor(settings: Settings) -> int:
    LOG.info("monitor started; stop with Ctrl+C")
    previous_key: tuple[str, tuple[tuple[str, int, int], ...]] | None = None
    active: ActiveSave | None = None
    try:
        while True:
            try:
                active = resolve_active_save(
                    settings.save_root,
                    override=settings.save_override,
                )
                key = (active.save_id, activity_signature(active))
                if key != previous_key:
                    scan_once(settings, active=active)
                    previous_key = key
                elif settings.publish.enabled:
                    GitSync(settings.publish).publish_if_dirty(
                        save_name=active.folder_name,
                        updated_at=utc_now(),
                    )
            except Exception as exc:
                _write_failure(settings, active, exc)
            time.sleep(settings.poll_seconds)
    except KeyboardInterrupt:
        LOG.info("monitor stopped by user")
        return 0


def _telemetry_signature(settings: Settings) -> tuple[tuple[str, int, int], ...]:
    result: list[tuple[str, int, int]] = []
    for name in ("pzmb_current_state.json", "pzmb_status.json"):
        path = settings.telemetry_dir / name
        if not path.is_file():
            return ()
        stat = path.stat()
        result.append((name, stat.st_size, stat.st_mtime_ns))
    request = settings.telemetry_dir / "pzmb_calculation_request.json"
    if request.is_file():
        stat = request.stat()
        result.append((request.name, stat.st_size, stat.st_mtime_ns))
    return tuple(result)


def _stable_telemetry_signature(
    settings: Settings,
) -> tuple[tuple[str, int, int], ...]:
    """Wait until both mod JSON files stop changing before reading them."""
    candidate = _telemetry_signature(settings)
    if not candidate:
        return ()

    required = max(1, settings.stable_polls)
    stable = 1
    while stable < required:
        time.sleep(max(0.0, settings.stable_interval_seconds))
        current = _telemetry_signature(settings)
        if not current:
            return ()
        if current == candidate:
            stable += 1
        else:
            candidate = current
            stable = 1
    return candidate


def monitor_mod(settings: Settings) -> int:
    """Run one relay monitor per workspace, even after accidental double start."""
    try:
        with single_instance(settings.runtime_dir / "relay-monitor.lock"):
            return _monitor_mod_locked(settings)
    except InstanceAlreadyRunning:
        LOG.info("mod telemetry relay is already running; duplicate exits")
        return 0


def _monitor_mod_locked(settings: Settings) -> int:
    """Watch only mod telemetry; never open a Project Zomboid save."""
    LOG.info("mod telemetry relay started; stop with Ctrl+C")
    previous: tuple[tuple[str, int, int], ...] | None = None
    try:
        while True:
            try:
                current = _telemetry_signature(settings)
                if current and current != previous:
                    stable = _stable_telemetry_signature(settings)
                    if stable and stable != previous:
                        result = relay_once(settings)
                        previous = stable
                        LOG.info(
                            "relay ok items=%s changes=%s publication=%s",
                            result["items"],
                            len(result["changes"]),
                            result["publication"],
                        )
            except Exception:
                LOG.exception("mod telemetry relay failed")
            time.sleep(settings.poll_seconds)
    except KeyboardInterrupt:
        LOG.info("mod telemetry relay stopped by user")
        return 0

def add_base_here(
    settings: Settings,
    *,
    name: str,
    radius: float,
) -> dict[str, Any]:
    active = resolve_active_save(
        settings.save_root,
        override=settings.save_override,
    )
    wait_stable(
        active.path / "players.db",
        polls=settings.stable_polls,
        interval=settings.stable_interval_seconds,
    )
    _, _, player = read_player_snapshot(active.path / "players.db")
    position = player["position"]
    zone = {
        "id": f"base-{active.save_id}-{len(settings.base_zones) + 1}",
        "name": name,
        "save_id": active.save_id,
        "shape": "circle",
        "x": float(position["x"]),
        "y": float(position["y"]),
        "radius": float(radius),
    }
    raw = json.loads(settings.config_path.read_text(encoding="utf-8-sig"))
    raw.setdefault("base_zones", []).append(zone)
    atomic_write_json(settings.config_path, raw)
    return zone


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pzbot",
        description="Read-only Project Zomboid Build 42.20.3 resource monitor",
    )
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("scan", help="Create one safe snapshot and update live JSON")
    commands.add_parser("monitor", help="Watch the active save in the foreground")
    commands.add_parser("status", help="Print the last local status")
    commands.add_parser(
        "relay",
        help="Process one snapshot written by the in-game mod",
    )
    commands.add_parser(
        "relay-monitor",
        help="Watch mod telemetry in foreground; stop with Ctrl+C",
    )

    base = commands.add_parser("base", help="Manage owned base zones")
    base_commands = base.add_subparsers(dest="base_command", required=True)
    set_here = base_commands.add_parser(
        "set-here",
        help="Use the current player position as a base center",
    )
    set_here.add_argument("--name", default="Main base")
    set_here.add_argument("--radius", type=float, default=30.0)
    return parser


def main() -> int:
    args = _parser().parse_args()
    settings = load_settings(args.config)
    _configure_logging(settings, args.verbose)
    active: ActiveSave | None = None
    try:
        if args.command == "scan":
            print(json.dumps(scan_once(settings), ensure_ascii=False, indent=2))
            return 0
        if args.command == "monitor":
            return monitor(settings)
        if args.command == "relay":
            print(json.dumps(relay_once(settings), ensure_ascii=False, indent=2))
            return 0
        if args.command == "relay-monitor":
            return monitor_mod(settings)
        if args.command == "status":
            status_path = settings.live_dir / "status.json"
            if not status_path.is_file():
                raise FileNotFoundError("No status.json yet; run pzbot scan first")
            print(status_path.read_text(encoding="utf-8"))
            return 0
        if args.command == "base" and args.base_command == "set-here":
            zone = add_base_here(settings, name=args.name, radius=args.radius)
            print(json.dumps(zone, ensure_ascii=False, indent=2))
            return 0
        raise RuntimeError(f"Unsupported command: {args.command}")
    except Exception as exc:
        _write_failure(settings, active, exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

