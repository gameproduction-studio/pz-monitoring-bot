"""Relay in-game telemetry to the stable public JSON surface."""

from __future__ import annotations

import copy
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
    current_state["source"] = {
        "primary": "in_game_mod",
        "gameSaveReadByRelay": False,
        "modReportsReadOnlyGameState": True,
        "telemetrySequence": (raw.get("export") or {}).get("sequence"),
    }

    status = {
        "schema": "pz-monitoring-bot/status/v2",
        "schemaVersion": current_state["schemaVersion"],
        "contractRevision": 8,
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
    return {
        "save": snapshot.get("save"),
        "items": len(flatten_state(snapshot)),
        "changes": events,
        "publication": publication,
        "telemetrySequence": (raw.get("export") or {}).get("sequence"),
    }
