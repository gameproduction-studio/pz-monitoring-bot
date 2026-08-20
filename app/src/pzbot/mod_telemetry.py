"""Safe ingestion and normalization of telemetry written by the in-game mod."""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Any


class TelemetryReadError(RuntimeError):
    pass


def read_stable_json(
    path: Path,
    *,
    stable_polls: int = 2,
    interval_seconds: float = 0.15,
    attempts: int = 20,
) -> dict[str, Any]:
    """Read a complete mod JSON file without ever opening game saves."""
    previous: tuple[int, int] | None = None
    stable = 0
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            stat = path.stat()
            signature = (stat.st_size, stat.st_mtime_ns)
            if signature == previous and stat.st_size > 0:
                stable += 1
            else:
                previous = signature
                stable = 1
            if stable >= stable_polls:
                value = json.loads(path.read_text(encoding="utf-8-sig"))
                if not isinstance(value, dict):
                    raise TelemetryReadError(f"{path.name} root is not an object")
                return value
        except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
            last_error = exc
            stable = 0
        time.sleep(interval_seconds)
    detail = f": {last_error}" if last_error else ""
    raise TelemetryReadError(f"Telemetry did not stabilize: {path}{detail}")


def read_mod_telemetry(telemetry_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    state_path = telemetry_dir / "pzmb_current_state.json"
    status_path = telemetry_dir / "pzmb_status.json"
    state = read_stable_json(state_path)
    status = read_stable_json(status_path)
    if not status.get("ok") or not status.get("parsingSuccessful"):
        raise TelemetryReadError(f"Mod reported an export error: {status.get('error')}")
    state_sequence = int((state.get("export") or {}).get("sequence") or -1)
    status_sequence = int(status.get("sequence") or -2)
    if state_sequence != status_sequence:
        raise TelemetryReadError(
            f"State/status generation mismatch: {state_sequence} != {status_sequence}"
        )
    return state, status


def _normalized_item(item: dict[str, Any]) -> dict[str, Any]:
    item_id = str(item.get("itemId"))
    result: dict[str, Any] = {
        "fullType": item.get("fullType"),
        "itemIds": [item_id],
        "quantity": 1,
        "stackCountReportedByGame": item.get("quantity", 1),
        "name_ru": item.get("nameLocalized"),
        "nameLocalized": item.get("nameLocalized"),
        "localizationSource": "installed_game_runtime",
        "customName": item.get("customName"),
        "condition": item.get("condition"),
        "conditionMax": item.get("conditionMax"),
        "currentUses": item.get("currentUses"),
        "uses": item.get("uses"),
        "remainingFraction": (
            round(float(item.get("currentUses")) / float(item.get("uses")), 6)
            if isinstance(item.get("currentUses"), (int, float))
            and isinstance(item.get("uses"), (int, float))
            and float(item["uses"]) > 0
            else None
        ),
        "weight": item.get("weight"),
        "actualWeight": item.get("actualWeight"),
        "category": item.get("category"),
        "displayCategory": item.get("displayCategory"),
        "tags": copy.deepcopy(item.get("tags") or []),
        "equipped": bool(item.get("equipped")),
        "primaryHand": bool(item.get("primaryHand")),
        "secondaryHand": bool(item.get("secondaryHand")),
        "equippedLocations": [item["wornLocation"]] if item.get("wornLocation") else [],
        "attachedLocation": item.get("attachedLocation"),
        "favorite": bool(item.get("favorite")),
        "storage": copy.deepcopy(item.get("storage") or {}),
        "rawRuntimePath": item.get("locationPath"),
        "replaceOnUse": item.get("replaceOnUse"),
    }
    food = copy.deepcopy(item.get("food"))
    if food:
        result.update(
            itemType="food",
            food=food,
            age=food.get("ageDays"),
            offAge=food.get("daysFresh"),
            offAgeMax=food.get("daysTotallyRotten"),
            freshness=food.get("freshnessStage"),
            frozen=bool(food.get("frozen")),
            freezingTime=food.get("freezingTime"),
            cooked=bool(food.get("cooked")),
            burnt=bool(food.get("burnt")),
        )
    weapon = copy.deepcopy(item.get("weapon"))
    if weapon:
        result.update(itemType="weapon", weapon=weapon, **weapon)
    nested = item.get("container")
    if nested:
        result["itemType"] = result.get("itemType") or "container"
        result["portableContainer"] = {
            key: copy.deepcopy(value)
            for key, value in nested.items()
            if key != "items"
        }
        result["contents"] = [_normalized_item(child) for child in nested.get("items") or []]
    return {key: value for key, value in result.items() if value is not None}


def _normalized_container(container: dict[str, Any], world_age_hours: Any) -> dict[str, Any]:
    result = copy.deepcopy(container)
    result["items"] = [_normalized_item(item) for item in container.get("items") or []]
    observation = result.get("observation")
    last_seen = result.pop("lastSeenWorldAgeHours", None)
    stale = isinstance(last_seen, (int, float)) and isinstance(
        world_age_hours, (int, float)
    ) and float(last_seen) < float(world_age_hours) - 1e-6
    result["observation"] = {
        "method": observation if isinstance(observation, str) else "runtime",
        "lastSeenWorldAgeHours": last_seen,
        "stale": stale,
    }
    ownership = result.setdefault("ownership", {})
    ownership.setdefault("confidence", "exact" if ownership.get("owned") else "observed")
    return result


def _item_ids(items: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for item in items:
        result.update(str(value) for value in item.get("itemIds") or [])
        result.update(_item_ids(item.get("contents") or []))
    return result


def _without_known_items(items: list[dict[str, Any]], known: set[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items:
        ids = {str(value) for value in item.get("itemIds") or []}
        if ids & known:
            continue
        copied = copy.deepcopy(item)
        if copied.get("contents"):
            copied["contents"] = _without_known_items(copied["contents"], known)
        result.append(copied)
    return result


def normalize_mod_snapshot(
    raw: dict[str, Any],
    *,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    world_age_hours = (raw.get("game") or {}).get("worldAgeHours")
    """Convert runtime telemetry to the internal instance-level snapshot contract."""
    character = copy.deepcopy(raw.get("character") or {})
    inventory = character.setdefault("inventory", {})
    inventory["items"] = [
        _normalized_item(item) for item in inventory.get("items") or []
    ]
    current_containers = [
        _normalized_container(container, world_age_hours)
        for container in (raw.get("world") or {}).get("containers") or []
    ]

    known_now = _item_ids(inventory["items"])
    for container in current_containers:
        known_now.update(_item_ids(container.get("items") or []))

    current_ids = {str(container.get("containerId")) for container in current_containers}
    if previous and (previous.get("save") or {}).get("id") == (raw.get("save") or {}).get("id"):
        previous_by_id = {
            str(container.get("containerId")): container
            for container in (previous.get("world") or {}).get("containers") or []
        }
        for current in current_containers:
            old = previous_by_id.get(str(current.get("containerId")))
            old_ownership = (old or {}).get("ownership") or {}
            current_ownership = current.get("ownership") or {}
            if old_ownership.get("owned") and str(old_ownership.get("reason", "")).startswith("opened") and not current_ownership.get("owned"):
                current["ownership"] = copy.deepcopy(old_ownership)
                current["ownership"]["reason"] = "opened_previous_session"
                current["ownership"]["confidence"] = "exact_persisted_locally"
        for old in (previous.get("world") or {}).get("containers") or []:
            if str(old.get("containerId")) in current_ids:
                continue
            stale = copy.deepcopy(old)
            stale["items"] = _without_known_items(stale.get("items") or [], known_now)
            stale_observation = stale.get("observation")
            if not isinstance(stale_observation, dict):
                stale_observation = {"method": str(stale_observation or "previous_snapshot")}
            stale_observation["stale"] = True
            stale_observation["carriedForward"] = True
            stale["observation"] = stale_observation
            current_containers.append(stale)

    current_containers.sort(key=lambda value: str(value.get("containerId")))
    game = copy.deepcopy(raw.get("game") or {})
    return {
        "schema": "pz-monitoring-bot/internal-snapshot/v2",
        "save": copy.deepcopy(raw.get("save") or {}),
        "worldVersion": raw.get("worldVersion"),
        "game": game,
        "character": character,
        "world": {
            "containers": current_containers,
            "groundItems": [],
            "vehicles": [],
            "corpses": [
                container for container in current_containers if container.get("kind") == "corpse"
            ],
            "coverage": copy.deepcopy((raw.get("world") or {}).get("coverage") or {}),
        },
        "baseZones": copy.deepcopy(raw.get("baseZones") or []),
        "runtimeExport": copy.deepcopy(raw.get("export") or {}),
        "source": copy.deepcopy(raw.get("source") or {}),
    }
