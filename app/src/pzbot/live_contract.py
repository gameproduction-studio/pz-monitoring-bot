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
            "policy": "character_or_inside_saved_base_or_registered_vehicle",
            "baseZones": copy.deepcopy(snapshot.get("baseZones") or []),
            "persistentScope": "character_bases_registered_vehicles",
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
    recent_changes_total: int | None = None,
) -> dict[str, Any]:
    """Create a small connector-safe view without losing gameplay facts."""
    character = copy.deepcopy(current_state.get("character") or {})
    character.pop("inventory", None)

    views = copy.deepcopy(current_state.get("assistantViews") or {})
    views.pop("ownedItemsByLocation", None)
    views.pop("ownedCountsByFullType", None)

    location_rows: list[list[Any]] = []
    location_ids: dict[str, str] = {}

    def intern_location(location: dict[str, Any] | None) -> str | None:
        if not location:
            return None
        key = json.dumps(
            location,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        location_id = location_ids.get(key)
        if location_id is not None:
            return location_id
        location_id = f"L{len(location_rows) + 1}"
        location_ids[key] = location_id
        location_rows.append(
            [
                location_id,
                location.get("label"),
                location.get("path"),
                location.get("containerId"),
                location.get("position"),
                location.get("owned"),
                location.get("stale"),
                location.get("scope"),
                location.get("containerType"),
            ]
        )
        return location_id

    search = views.get("search") or {}
    raw_search_items = list(search.get("items") or [])

    resource_groups: dict[tuple[str, str], dict[str, Any]] = {}
    for item in raw_search_items:
        full_type = str(item.get("fullType") or "unknown")
        name_ru = str(item.get("name_ru") or full_type)
        key = (name_ru, full_type)
        record = resource_groups.setdefault(
            key,
            {
                "name_ru": name_ru,
                "quantity": 0,
                "onCharacter": 0,
                "locations": {},
                "conditionPercentMin": None,
                "conditionPercentMax": None,
                "fullType": full_type,
            },
        )
        record["quantity"] += 1
        if item.get("availability") == "in_character_inventory":
            record["onCharacter"] += 1
        location = item.get("location") or {}
        location_key = str(
            location.get("containerId") or location.get("path") or location.get("label")
        )
        location_record = record["locations"].setdefault(
            location_key,
            {
                "name_ru": location.get("label"),
                "quantity": 0,
                "position": location.get("position"),
                "containerId": location.get("containerId"),
                "scope": location.get("scope"),
                "loadedNow": not bool(location.get("stale")),
            },
        )
        location_record["quantity"] += 1
        condition = item.get("condition")
        condition_max = item.get("conditionMax")
        if (
            isinstance(condition, (int, float))
            and isinstance(condition_max, (int, float))
            and condition_max
        ):
            percent = round(float(condition) / float(condition_max) * 100.0, 1)
            minimum = record["conditionPercentMin"]
            maximum = record["conditionPercentMax"]
            record["conditionPercentMin"] = percent if minimum is None else min(minimum, percent)
            record["conditionPercentMax"] = percent if maximum is None else max(maximum, percent)

    resource_items: list[dict[str, Any]] = []
    for record in resource_groups.values():
        record["locations"] = sorted(
            record["locations"].values(),
            key=lambda value: (str(value.get("name_ru")), str(value.get("containerId"))),
        )
        resource_items.append(record)
    resource_items.sort(key=lambda value: (str(value.get("name_ru")), str(value.get("fullType"))))
    resource_view = {
        "instruction_ru": (
            "Основная сводка для ответов пользователю. Показывай name_ru и количество; "
            "itemId и fullType называй только по прямому запросу."
        ),
        "items": resource_items,
    }

    search_fields = [
        "itemId", "fullType", "name_ru", "category", "condition", "conditionMax",
        "isPortableContainer", "capacity", "weightReduction", "availability",
        "distanceTiles", "directionFromPlayer", "locationId",
    ]
    search_rows = []
    for item in raw_search_items:
        search_rows.append(
            [
                item.get("itemId"), item.get("fullType"), item.get("name_ru"),
                item.get("category"), item.get("condition"), item.get("conditionMax"),
                item.get("isPortableContainer"), item.get("capacity"),
                item.get("weightReduction"), item.get("availability"),
                item.get("distanceTiles"), item.get("directionFromPlayer"),
                intern_location(item.get("location")),
            ]
        )
    search["fields"] = search_fields
    search["items"] = search_rows

    food = views.get("food") or {}
    food_groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in food.get("owned") or []:
        location = item.get("location") or {}
        key = (
            item.get("fullType"), item.get("name_ru"), item.get("freshness"),
            bool(item.get("frozen")), bool(item.get("cooked")),
            bool(item.get("burnt")), bool(item.get("rotten")),
            location.get("containerId") or location.get("path"),
        )
        record = food_groups.setdefault(
            key,
            {
                "name_ru": item.get("name_ru"),
                "quantity": 0,
                "freshness": item.get("freshness"),
                "frozen": bool(item.get("frozen")),
                "freezingTime": item.get("freezingTime"),
                "cooked": bool(item.get("cooked")),
                "burnt": bool(item.get("burnt")),
                "rotten": bool(item.get("rotten")),
                "cookable": bool(item.get("cookable")),
                "dangerousUncooked": bool(item.get("dangerousUncooked")),
                "remainingFractionMin": item.get("remainingFraction"),
                "remainingFractionMax": item.get("remainingFraction"),
                "caloriesTotalReportedByGame": 0.0,
                "hoursUntilStaleAtRoomTemperature": item.get(
                    "hoursUntilStaleAtRoomTemperature"
                ),
                "hoursUntilRottenAtRoomTemperature": item.get(
                    "hoursUntilRottenAtRoomTemperature"
                ),
                "location": {
                    "name_ru": location.get("label"),
                    "position": location.get("position"),
                    "containerId": location.get("containerId"),
                    "storageType": location.get("containerType"),
                    "loadedNow": not bool(location.get("stale")),
                },
                "recipeOptions": item.get("recipeOptions") or [],
                "replaceOnCooked": item.get("replaceOnCooked") or [],
                "fullType": item.get("fullType"),
            },
        )
        record["quantity"] += 1
        record["caloriesTotalReportedByGame"] += float(
            item.get("caloriesReportedByGame") or 0
        )
        fraction = item.get("remainingFraction")
        if isinstance(fraction, (int, float)):
            minimum = record.get("remainingFractionMin")
            maximum = record.get("remainingFractionMax")
            record["remainingFractionMin"] = fraction if minimum is None else min(minimum, fraction)
            record["remainingFractionMax"] = fraction if maximum is None else max(maximum, fraction)
        for field in (
            "hoursUntilStaleAtRoomTemperature",
            "hoursUntilRottenAtRoomTemperature",
        ):
            value = item.get(field)
            current = record.get(field)
            if isinstance(value, (int, float)):
                record[field] = value if not isinstance(current, (int, float)) else min(current, value)

    food_summary = list(food_groups.values())
    for record in food_summary:
        record["caloriesTotalReportedByGame"] = round(
            record["caloriesTotalReportedByGame"], 2
        )
    food_summary.sort(
        key=lambda value: (
            not bool(value.get("rotten")),
            value.get("hoursUntilRottenAtRoomTemperature") is None,
            value.get("hoursUntilRottenAtRoomTemperature") or float("inf"),
            str(value.get("name_ru")),
        )
    )
    food_view = {
        "instruction_ru": (
            "Используй эту сводку для еды: здесь сохранены русское название, свежесть, "
            "заморозка, приготовленность, оставшаяся доля, калории и место хранения."
        ),
        "summary": food_summary,
        "highCalorieSummary": sorted(
            food_summary,
            key=lambda value: -float(value.get("caloriesTotalReportedByGame") or 0),
        )[:15],
        "cookingSummary": [
            {
                "name_ru": value.get("name_ru"),
                "quantity": value.get("quantity"),
                "cookable": value.get("cookable"),
                "dangerousUncooked": value.get("dangerousUncooked"),
                "location": value.get("location"),
                "recipeOptions": value.get("recipeOptions") or [],
            }
            for value in food_summary
            if value.get("cookable")
            or value.get("recipeOptions")
            or value.get("replaceOnCooked")
        ],
        "spoilageAlerts": food.get("spoilageAlerts") or [],
        "totalCaloriesReportedByGame": food.get("totalCaloriesReportedByGame"),
    }

    locations_view = {
        "fields": [
            "locationId", "label", "path", "containerId", "position", "owned",
            "stale", "scope", "containerType",
        ],
        "items": location_rows,
    }
    contract = views.get("contract") or {}
    contract["readOrder"] = (
        "Read overview, character, bases, recentChanges, vehicles.owned, food.summary, "
        "and resources.items in that order."
    )
    contract["compactRows"] = (
        "The public file intentionally omits duplicate instance indexes. Human resource, "
        "food, base, and vehicle summaries are normal named objects."
    )
    vehicle_view = views.get("vehicles") or {}
    views = {
        "contract": contract,
        "vehicles": vehicle_view,
        "food": food_view,
        "resources": resource_view,
        "ownedItemCount": views.get("ownedItemCount"),
        "observedOnlyItemCount": views.get("observedOnlyItemCount"),
    }

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
                "loadedNow": not bool((value.get("observation") or {}).get("stale")),
                "stateStatus": (
                    "last_confirmed_stable_while_unloaded"
                    if (value.get("observation") or {}).get("stale")
                    else "live_loaded"
                ),
            }
            for value in values
        ]

    recent_limit = 100
    recent_changes = copy.deepcopy((events or [])[-recent_limit:])
    detected_change_count = (
        len(events or []) if recent_changes_total is None else recent_changes_total
    )
    recent_changes_meta = {
        "totalDetected": detected_change_count,
        "returned": len(recent_changes),
        "limit": recent_limit,
        "truncated": detected_change_count > len(recent_changes),
    }
    container_rows = container_index(world.get("containers") or [])
    ownership = copy.deepcopy(current_state.get("ownership") or {})
    base_summaries = []
    for zone in ownership.get("baseZones") or []:
        zone_id = zone.get("id")
        zone_containers = [
            row for row in container_rows
            if (row.get("ownership") or {}).get("baseZoneId") == zone_id
        ]
        loaded_count = sum(1 for row in zone_containers if row.get("loadedNow"))
        base_summaries.append(
            {
                "id": zone_id,
                "name": zone.get("name"),
                "center": {
                    "x": zone.get("x"),
                    "y": zone.get("y"),
                    "z": zone.get("z"),
                },
                "radius": zone.get("radius"),
                "minZ": zone.get("minZ"),
                "maxZ": zone.get("maxZ"),
                "containerCount": len(zone_containers),
                "itemInstances": sum(
                    int(row.get("itemInstances") or 0) for row in zone_containers
                ),
                "loadedContainersNow": loaded_count,
                "lastKnownContainers": len(zone_containers) - loaded_count,
                "stateStatus": (
                    "live_loaded" if loaded_count
                    else "last_confirmed_stable_while_unloaded" if zone_containers
                    else "not_scanned"
                ),
                "containers": zone_containers,
            }
        )

    vehicle_briefs = []
    for vehicle in vehicle_view.get("owned") or []:
        vehicle_briefs.append(
            {
                "name": vehicle.get("name"),
                "displayName": vehicle.get("displayName"),
                "scriptFullType": vehicle.get("scriptFullType"),
                "position": vehicle.get("position"),
                "loadedNow": vehicle.get("loadedNow"),
                "stateStatus": vehicle.get("stateStatus"),
                "fuel": vehicle.get("fuel"),
                "batteryChargePercent": vehicle.get("batteryChargePercent"),
                "overallConditionPercent": vehicle.get("overallConditionPercent"),
                "engine": vehicle.get("engine"),
                "cargoContainers": vehicle.get("cargoContainers") or [],
                "alerts": vehicle.get("alerts") or [],
            }
        )

    overview = {
        "instruction_ru": (
            "Читай этот блок первым. Он всегда содержит персонажа, базы и автомобили "+
            "до длинных списков еды и ресурсов."
        ),
        "character": copy.deepcopy(character),
        "bases": base_summaries,
        "vehicles": vehicle_briefs,
        "coverage": copy.deepcopy(world.get("coverage") or {}),
        "resourceGroups": len(resource_items),
        "foodGroups": len(food_summary),
        "recentChanges": recent_changes_meta,
    }

    state = {
        "schema": "pz-monitoring-bot/chatgpt-state/v3",
        "schemaVersion": current_state.get("schemaVersion"),
        "status": copy.deepcopy(status or {}),
        "updatedAt": current_state.get("updatedAt"),
        "game": copy.deepcopy(current_state.get("game") or {}),
        "save": copy.deepcopy(current_state.get("save") or {}),
        "overview": overview,
        "character": character,
        "bases": base_summaries,
        "recentChanges": recent_changes,
        "recentChangesMeta": recent_changes_meta,
        "assistantViews": views,
        "ownership": ownership,
        "summary": copy.deepcopy(current_state.get("summary") or {}),
        "source": copy.deepcopy(current_state.get("source") or {}),
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


def _same_public_export(
    previous_public: dict[str, Any],
    status: dict[str, Any],
) -> bool:
    previous_status = previous_public.get("status") or {}
    previous_save = (previous_status.get("activeSave") or {}).get("id")
    current_save = (status.get("activeSave") or {}).get("id")
    previous_sequence = (previous_status.get("modStatus") or {}).get("sequence")
    current_sequence = (status.get("modStatus") or {}).get("sequence")
    return (
        previous_save == current_save
        and previous_sequence is not None
        and previous_sequence == current_sequence
        and previous_status.get("contractRevision") == status.get("contractRevision")
        and previous_status.get("monitoringScope") == status.get("monitoringScope")
    )

def write_live_files(
    live_dir: Path,
    *,
    current_state: dict[str, Any],
    status: dict[str, Any],
    events: list[dict[str, Any]],
) -> None:
    live_dir.mkdir(parents=True, exist_ok=True)
    public_path = live_dir / "chatgpt_state.json"
    public_status = copy.deepcopy(status)
    public_events = list(events)
    public_total = len(events)
    reuse_previous_public = False
    if not events and public_path.is_file():
        try:
            previous_public = json.loads(public_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            previous_public = {}
        if _same_public_export(previous_public, public_status):
            reuse_previous_public = True
            public_events = copy.deepcopy(previous_public.get("recentChanges") or [])
            previous_meta = previous_public.get("recentChangesMeta") or {}
            public_total = int(previous_meta.get("totalDetected") or len(public_events))
            previous_status = previous_public.get("status") or {}
            public_status["changesThisScan"] = previous_status.get(
                "changesThisScan", public_total
            )

    # Local current_state remains a rich diagnostic file. The public connector
    # receives the compact, scope-limited assistant surface only.
    atomic_write_json(live_dir / "current_state.json", current_state, compact=True)
    if not reuse_previous_public:
        atomic_write_json(
            public_path,
            build_chatgpt_state(
                current_state,
                status=public_status,
                events=public_events,
                recent_changes_total=public_total,
            ),
            compact=True,
        )
    append_changes(live_dir / "changes.jsonl", events)
    atomic_write_json(live_dir / "status.json", public_status)

