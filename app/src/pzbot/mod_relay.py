"""Relay in-game telemetry to the stable public JSON surface."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from .assistant_views import build_assistant_views
from .git_sync import GitSync
from .live_contract import (
    build_current_state,
    load_local_state,
    previous_for_save,
    save_local_state,
    update_local_state,
    utc_now,
    write_live_files,
)
from .mod_telemetry import (
    normalize_mod_snapshot,
    read_mod_telemetry,
    restrict_to_persistent_scope,
)
from .settings import Settings
from .state_diff import compare_states, flatten_state
from .supply_calculations import build_supply_calculations
from .jsonio import atomic_write_json


CALCULATION_REQUEST = "pzmb_calculation_request.json"
CALCULATION_RESPONSE = "pzmb_calculation_response.txt"
CALCULATION_SCHEMA = "pz-monitoring-bot/supply-calculations/v2"


def _calculation_request(settings: Settings) -> dict[str, Any] | None:
    path = settings.telemetry_dir / CALCULATION_REQUEST
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or not value.get("requestId"):
        return None
    return value


def _cached_calculations(settings: Settings) -> dict[str, Any] | None:
    path = settings.runtime_dir / "supply_calculations.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_calculation_response(
    settings: Settings, request_id: str, *, ok: bool, message: str
) -> None:
    path = settings.telemetry_dir / CALCULATION_RESPONSE
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    safe_message = str(message).replace("\t", " ").replace("\r", " ").replace("\n", " ")
    temporary.write_text(
        f"{request_id}\t{'ok' if ok else 'error'}\t{safe_message}\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def relay_once(settings: Settings) -> dict[str, Any]:
    raw, mod_status = read_mod_telemetry(settings.telemetry_dir)
    scan_time = utc_now()
    local_state = load_local_state(settings.state_path)
    save_id = str((raw.get("save") or {}).get("id"))
    previous = previous_for_save(local_state, save_id)
    previous = restrict_to_persistent_scope(previous)
    snapshot = normalize_mod_snapshot(raw, previous=previous)
    events = compare_states(previous, snapshot, timestamp=scan_time)
    current_state = build_current_state(snapshot, events=events, scan_time=scan_time)
    current_state["assistantViews"] = build_assistant_views(snapshot)
    request = _calculation_request(settings)
    calculations = _cached_calculations(settings)
    calculation_error = None
    raw_sequence = int((raw.get("export") or {}).get("sequence") or 0)
    request_matches_snapshot = bool(
        request and int(request.get("snapshotSequence") or -1) == raw_sequence
    )
    if request_matches_snapshot and (
        not calculations
        or calculations.get("requestId") != request.get("requestId")
        or calculations.get("schema") != CALCULATION_SCHEMA
    ):
        try:
            calculations = build_supply_calculations(
                snapshot,
                game_path=settings.game_path,
                request=request,
                created_at=scan_time,
            )
            atomic_write_json(
                settings.runtime_dir / "supply_calculations.json",
                calculations,
                compact=True,
            )
        except Exception as exc:
            calculation_error = f"{type(exc).__name__}: {exc}"
    calculation_current = bool(
        calculations
        and calculations.get("saveId") == save_id
        and int(calculations.get("snapshotSequence") or -1) == raw_sequence
    )
    current_state["supplyCalculations"] = copy.deepcopy(calculations or {})
    current_state["source"] = {
        "primary": "in_game_mod",
        "gameSaveReadByRelay": False,
        "modReportsReadOnlyGameState": True,
        "telemetrySequence": (raw.get("export") or {}).get("sequence"),
        "calculationsReady": calculation_current and calculation_error is None,
    }

    status = {
        "schema": "pz-monitoring-bot/status/v2",
        "schemaVersion": current_state["schemaVersion"],
        "contractRevision": 10,
        "monitoringScope": "character_bases_registered_vehicles",
        "ok": True,
        "parsingSuccessful": True,
        "lastScanAt": scan_time,
        "lastGameExportEpochMs": (raw.get("export") or {}).get("writtenAtEpochMs"),
        "activeSave": copy.deepcopy(snapshot.get("save") or {}),
        "game": copy.deepcopy(snapshot.get("game") or {}),
        "coverage": copy.deepcopy((snapshot.get("world") or {}).get("coverage") or {}),
        "changesThisScan": len(events),
        "itemInstances": len(flatten_state(snapshot)),
        "publication": "automatic_direct_push_to_main" if settings.publish.enabled else "local_only",
        "readOnlySource": True,
        "relayReadGameSave": False,
        "modStatus": mod_status,
        "calculations": {
            "ready": calculation_current and calculation_error is None,
            "currentForSnapshot": calculation_current,
            "requestId": (calculations or {}).get("requestId"),
            "snapshotSequence": (calculations or {}).get("snapshotSequence"),
            "createdAt": (calculations or {}).get("createdAt"),
            "error": calculation_error,
        },
    }
    write_live_files(
        settings.live_dir,
        current_state=current_state,
        status=status,
        events=events,
    )
    update_local_state(local_state, snapshot, scan_time=scan_time)
    save_local_state(settings.state_path, local_state)
    publication = GitSync(settings.publish).publish_if_dirty(
        save_name=str((snapshot.get("save") or {}).get("name") or "unknown"),
        updated_at=scan_time,
    )
    if request_matches_snapshot and request:
        if calculation_error:
            _write_calculation_response(
                settings, str(request["requestId"]), ok=False, message=calculation_error
            )
        elif calculation_current:
            _write_calculation_response(
                settings,
                str(request["requestId"]),
                ok=True,
                message="completed_and_published",
            )
    return {
        "save": snapshot.get("save"),
        "items": len(flatten_state(snapshot)),
        "changes": events,
        "publication": publication,
        "telemetrySequence": (raw.get("export") or {}).get("sequence"),
        "calculationsReady": calculation_current and calculation_error is None,
    }
