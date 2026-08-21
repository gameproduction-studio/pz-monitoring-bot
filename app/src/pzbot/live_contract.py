"""Public JSON contract and durable local synchronization state."""

from __future__ import annotations

import copy
import datetime as dt
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from .jsonio import atomic_write_json
from .state_diff import flatten_state


SCHEMA_VERSION = "1.1.0"
BUILD_COMPATIBILITY = ["42.20.2", "42.20.3"]
MAX_PUBLIC_CHANGES_BYTES = 900_000
TARGET_PUBLIC_CHANGES_BYTES = 750_000


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load_local_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "schema": "pz-monitoring-bot/local-state/v1",
            "statesBySaveId": {},
        }
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_local_state(path: Path, state: dict[str, Any]) -> None:
    atomic_write_json(path, state)


def update_local_state(
    state: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    scan_time: str,
) -> None:
    save_id = snapshot["save"]["id"]
    state.setdefault("statesBySaveId", {})[save_id] = {
        "lastSuccessfulScanAt": scan_time,
        "snapshot": snapshot,
    }
    state["activeSaveId"] = save_id
    state["updatedAt"] = scan_time


def previous_for_save(
    state: dict[str, Any],
    save_id: str,
) -> dict[str, Any] | None:
    record = (state.get("statesBySaveId") or {}).get(save_id)
    return record.get("snapshot") if record else None


def build_current_state(
    snapshot: dict[str, Any],
    *,
    events: list[dict[str, Any]],
    scan_time: str,
) -> dict[str, Any]:
    instances = flatten_state(snapshot)
    items = sorted(
        instances.values(),
        key=lambda item: (
            str((item.get("source") or {}).get("path")),
            str(item.get("fullType")),
            str(item.get("itemId")),
        ),
    )
    total_counts = Counter(item.get("fullType") for item in items)
    owned_items = [
        item for item in items if bool((item.get("source") or {}).get("owned"))
    ]
    owned_counts = Counter(item.get("fullType") for item in owned_items)
    character_items = [
        item
        for item in items
        if (item.get("source") or {}).get("scope") == "character"
    ]
    world = snapshot.get("world") or {}
    containers = world.get("containers") or []
    vehicle_containers = [
        container
        for vehicle in world.get("vehicles") or []
        for container in vehicle.get("containers") or []
    ]
    all_containers = list(containers) + vehicle_containers
    owned_containers = [
        container
        for container in all_containers
        if (container.get("ownership") or {}).get("owned")
    ]

    character = copy.deepcopy(snapshot.get("character") or {})
    character.pop("inventoryOffset", None)
    current_world = copy.deepcopy(world)
    current_world.pop("chunks", None)

    return {
        "schema": "pz-monitoring-bot/current-state/v1",
        "schemaVersion": SCHEMA_VERSION,
        "updatedAt": scan_time,
        "game": {
            "build": (snapshot.get("game") or {}).get("build") or "42.20.3",
            "compatibleBuilds": BUILD_COMPATIBILITY,
            "worldVersion": snapshot.get("worldVersion"),
            "worldAgeHours": (snapshot.get("game") or {}).get("worldAgeHours"),
        },
        "save": copy.deepcopy(snapshot["save"]),
        "ownership": {
            "policy": "opened_or_inside_base_zone_or_registered_vehicle",
            "baseZones": copy.deepcopy(snapshot.get("baseZones") or []),
            "openedInferenceWarning": (
                "explored usually means opened in Build 42, but some game systems "
                "can set it automatically; inspect ownership.confidence."
            ),
        },
        "summary": {
            "physicalItemsVisible": len(items),
            "characterItems": len(character_items),
            "ownedItems": len(owned_items),
            "worldObservedItems": len(items) - len(character_items),
            "containersVisible": len(all_containers),
            "ownedContainers": len(owned_containers),
            "observedContainers": len(all_containers) - len(owned_containers),
            "corpsesVisible": len(world.get("corpses") or []),
            "groundItemsVisible": len(world.get("groundItems") or []),
            "vehiclesVisible": len(world.get("vehicles") or []),
            "changesThisScan": len(events),
        },
        "countsByFullType": dict(sorted(total_counts.items())),
        "ownedCountsByFullType": dict(sorted(owned_counts.items())),
        "character": character,
        "world": current_world,
        "itemList": {
            "omittedFromPublicSnapshot": True,
            "reason": "duplicate_of_world_and_assistant_search_index",
            "count": len(items),
        },
        "recentChanges": {
            "omittedFromCurrentState": True,
            "source": "changes.jsonl",
            "count": len(events),
        },
    }


def _without_none_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_none_values(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [_without_none_values(item) for item in value]
    return value


def build_chatgpt_state(
    current_state: dict[str, Any],
    *,
    status: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a connector-safe view without losing decision-relevant facts."""
    character = copy.deepcopy(current_state.get("character") or {})
    character.pop("inventory", None)

    views = copy.deepcopy(current_state.get("assistantViews") or {})
    views.pop("ownedItemsByLocation", None)
    for item in ((views.get("search") or {}).get("items") or []):
        item.pop("tags", None)
    food = views.get("food") or {}
    food.pop("highCalorieOwned", None)
    food.pop("cookingCandidates", None)

    world = current_state.get("world") or {}

    def container_index(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "containerId": value.get("containerId"),
                "kind": value.get("kind"),
                "displayName": value.get("displayName"),
                "position": value.get("position"),
                "ownership": value.get("ownership"),
                "refrigerator": value.get("refrigerator"),
                "freezer": value.get("freezer"),
                "vehicleId": value.get("vehicleId"),
                "vehicleName": value.get("vehicleName"),
                "itemInstances": len(value.get("items") or []),
            }
            for value in values
        ]

    state = {
        "schema": "pz-monitoring-bot/chatgpt-state/v1",
        "status": copy.deepcopy(status or {}),
        "schemaVersion": current_state.get("schemaVersion"),
        "updatedAt": current_state.get("updatedAt"),
        "game": copy.deepcopy(current_state.get("game") or {}),
        "save": copy.deepcopy(current_state.get("save") or {}),
        "ownership": copy.deepcopy(current_state.get("ownership") or {}),
        "summary": copy.deepcopy(current_state.get("summary") or {}),
        "countsByFullType": copy.deepcopy(
            current_state.get("countsByFullType") or {}
        ),
        "ownedCountsByFullType": copy.deepcopy(
            current_state.get("ownedCountsByFullType") or {}
        ),
        "character": character,
        "worldIndex": {
            "coverage": copy.deepcopy(world.get("coverage") or {}),
            "containers": container_index(world.get("containers") or []),
            "corpses": container_index(world.get("corpses") or []),
        },
        "assistantViews": views,
        "source": copy.deepcopy(current_state.get("source") or {}),
        "recentChanges": copy.deepcopy((events or [])[-100:]),
    }
    return _without_none_values(state)


def build_status(
    snapshot: dict[str, Any],
    *,
    scan_time: str,
    save_write_time: str,
    events: list[dict[str, Any]],
    publish_state: str,
) -> dict[str, Any]:
    world = snapshot.get("world") or {}
    return {
        "schema": "pz-monitoring-bot/status/v1",
        "schemaVersion": SCHEMA_VERSION,
        "ok": True,
        "parsingSuccessful": True,
        "lastSaveWriteAt": save_write_time,
        "lastScanAt": scan_time,
        "activeSave": copy.deepcopy(snapshot["save"]),
        "game": {
            "build": "42.20.3",
            "worldVersion": snapshot.get("worldVersion"),
        },
        "coverage": {
            "character": {"complete": True},
            "worldChunks": copy.deepcopy(world.get("coverage") or {}),
            "vehicles": copy.deepcopy(world.get("vehicleCoverage") or {}),
        },
        "changesThisScan": len(events),
        "publication": publish_state,
        "readOnlySource": True,
    }


def build_error_status(
    *,
    save: dict[str, Any] | None,
    error: str,
    scan_time: str | None = None,
) -> dict[str, Any]:
    return {
        "schema": "pz-monitoring-bot/status/v1",
        "schemaVersion": SCHEMA_VERSION,
        "ok": False,
        "parsingSuccessful": False,
        "lastScanAt": scan_time or utc_now(),
        "activeSave": save,
        "error": error,
        "readOnlySource": True,
    }


def append_changes(path: Path, events: list[dict[str, Any]]) -> None:
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for event in events:
            stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
            stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())

    if path.stat().st_size <= MAX_PUBLIC_CHANGES_BYTES:
        return
    data = path.read_bytes()
    tail = data[-TARGET_PUBLIC_CHANGES_BYTES:]
    first_newline = tail.find(b"\n")
    if first_newline >= 0:
        tail = tail[first_newline + 1 :]
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(tail)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def write_live_files(
    live_dir: Path,
    *,
    current_state: dict[str, Any],
    status: dict[str, Any],
    events: list[dict[str, Any]],
) -> None:
    live_dir.mkdir(parents=True, exist_ok=True)
    # current_state can contain more than a thousand rich item records. Compact
    # encoding plus omission of the duplicate flat list keeps it below the
    # ordinary ChatGPT source-size limit without discarding world facts.
    atomic_write_json(live_dir / "current_state.json", current_state, compact=True)
    atomic_write_json(
        live_dir / "chatgpt_state.json",
        build_chatgpt_state(
            current_state,
            status=status,
            events=events,
        ),
        compact=True,
    )
    append_changes(live_dir / "changes.jsonl", events)
    atomic_write_json(live_dir / "status.json", status)

