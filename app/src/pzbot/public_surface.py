"""Connector-safe, paged public telemetry for ordinary ChatGPT sessions."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from .jsonio import atomic_write_json


MAX_CHATGPT_FILE_BYTES = 90_000


def _encoded(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _snapshot(public_state: dict[str, Any]) -> dict[str, Any]:
    status = public_state.get("status") or {}
    return {
        "updatedAt": public_state.get("updatedAt"),
        "lastScanAt": status.get("lastScanAt"),
        "lastGameExportEpochMs": status.get("lastGameExportEpochMs"),
        "saveId": (public_state.get("save") or {}).get("id"),
        "sequence": (status.get("modStatus") or {}).get("sequence"),
    }


def _page_records(
    *,
    schema: str,
    snapshot: dict[str, Any],
    records: list[Any],
    instruction_ru: str,
) -> list[dict[str, Any]]:
    pages: list[list[Any]] = []
    current: list[Any] = []
    for record in records:
        candidate = current + [record]
        probe = {
            "schema": schema,
            "snapshot": snapshot,
            "instruction_ru": instruction_ru,
            "page": 9999,
            "pageCount": 9999,
            "records": candidate,
        }
        if current and len(_encoded(probe)) > MAX_CHATGPT_FILE_BYTES:
            pages.append(current)
            current = [record]
        else:
            current = candidate
    if current or not pages:
        pages.append(current)

    result = []
    for index, page in enumerate(pages, start=1):
        result.append(
            {
                "schema": schema,
                "snapshot": snapshot,
                "instruction_ru": instruction_ru,
                "page": index,
                "pageCount": len(pages),
                "records": page,
            }
        )
    return result


def _flatten_character_items(
    items: list[dict[str, Any]],
    *,
    parent_path: str = "Основной инвентарь",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        row = copy.deepcopy(item)
        contents = list(row.pop("contents", []) or [])
        portable = row.get("portableContainer") or {}
        row["containerPath_ru"] = parent_path
        rows.append(row)
        if contents:
            name = row.get("name_ru") or row.get("nameLocalized") or row.get("fullType")
            item_ids = row.get("itemIds") or []
            suffix = f" #{item_ids[0]}" if item_ids else ""
            rows.extend(
                _flatten_character_items(
                    contents,
                    parent_path=f"{parent_path} / {name}{suffix}",
                )
            )
        elif portable and row.get("quantity", 0) > 1:
            row["note_ru"] = "Содержимое сгруппированных экземпляров в этом снимке пусто."
    return rows


def build_public_files(
    current_state: dict[str, Any],
    public_state: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Return shard payloads, manifest, and the backwards-compatible bootstrap."""
    snapshot = _snapshot(public_state)
    files: dict[str, dict[str, Any]] = {}

    section_paths = {
        "overview": "live/chatgpt/overview.json",
        "character": "live/chatgpt/character.json",
        "bases": "live/chatgpt/bases.json",
        "vehicles": "live/chatgpt/vehicles.json",
        "food": "live/chatgpt/food.json",
        "changes": "live/chatgpt/changes.json",
        "resources": "live/chatgpt/resources.json",
    }

    files["overview.json"] = {
        "schema": "pz-monitoring-bot/chatgpt-overview/v1",
        "snapshot": snapshot,
        "instruction_ru": (
            "Начинай с этого файла. Для подробностей открывай только нужный раздел "
            "из sectionPaths; не пытайся читать все страницы без необходимости."
        ),
        "status": copy.deepcopy(public_state.get("status") or {}),
        "game": copy.deepcopy(public_state.get("game") or {}),
        "save": copy.deepcopy(public_state.get("save") or {}),
        "overview": copy.deepcopy(public_state.get("overview") or {}),
        "ownership": copy.deepcopy(public_state.get("ownership") or {}),
        "summary": copy.deepcopy(public_state.get("summary") or {}),
        "source": copy.deepcopy(public_state.get("source") or {}),
        "sectionPaths": section_paths,
    }

    character = copy.deepcopy(current_state.get("character") or {})
    inventory = character.pop("inventory", {}) or {}
    character_rows = _flatten_character_items(list(inventory.get("items") or []))
    character_pages = _page_records(
        schema="pz-monitoring-bot/chatgpt-character-items/v1",
        snapshot=snapshot,
        records=character_rows,
        instruction_ru=(
            "Предметы персонажа. Показывай name_ru; FullType и itemIds используй для "
            "сопоставления, но не вместо названий. containerPath_ru показывает вложенность."
        ),
    )
    character_refs = []
    for index, payload in enumerate(character_pages, start=1):
        name = f"character-items-{index:03d}.json"
        files[name] = payload
        character_refs.append(f"live/chatgpt/{name}")
    files["character.json"] = {
        "schema": "pz-monitoring-bot/chatgpt-character/v1",
        "snapshot": snapshot,
        "instruction_ru": "Основные данные персонажа и ссылки на все страницы его предметов.",
        "character": character,
        "inventoryItemGroups": len(character_rows),
        "inventoryPages": character_refs,
    }

    files["bases.json"] = {
        "schema": "pz-monitoring-bot/chatgpt-bases/v1",
        "snapshot": snapshot,
        "instruction_ru": (
            "Зарегистрированные базы и контейнеры. Содержимое ищи по locations в "
            "страницах resources, фильтруя baseZoneId/containerId."
        ),
        "bases": copy.deepcopy(public_state.get("bases") or []),
        "resourceIndex": section_paths["resources"],
    }

    vehicle_view = copy.deepcopy(
        ((public_state.get("assistantViews") or {}).get("vehicles") or {})
    )
    vehicle_records = list(vehicle_view.pop("owned", []) or [])
    vehicle_index = []
    for index, vehicle in enumerate(vehicle_records, start=1):
        name = f"vehicle-{index:03d}.json"
        files[name] = {
            "schema": "pz-monitoring-bot/chatgpt-vehicle/v1",
            "snapshot": snapshot,
            "instruction_ru": "Полное последнее подтверждённое состояние одного автомобиля.",
            "vehicle": vehicle,
        }
        vehicle_index.append(
            {
                "name": vehicle.get("name"),
                "displayName": vehicle.get("displayName"),
                "scriptFullType": vehicle.get("scriptFullType"),
                "position": vehicle.get("position"),
                "loadedNow": vehicle.get("loadedNow"),
                "stale": vehicle.get("stale"),
                "stateStatus": vehicle.get("stateStatus"),
                "fuel": vehicle.get("fuel"),
                "batteryChargePercent": vehicle.get("batteryChargePercent"),
                "overallConditionPercent": vehicle.get("overallConditionPercent"),
                "detailFile": f"live/chatgpt/{name}",
            }
        )
    files["vehicles.json"] = {
        "schema": "pz-monitoring-bot/chatgpt-vehicles/v1",
        "snapshot": snapshot,
        "instruction_ru": "Индекс закреплённых автомобилей; detailFile содержит детали и груз.",
        "owned": vehicle_index,
        "alerts": vehicle_view.get("alerts") or [],
        "staleRule": vehicle_view.get("staleRule"),
    }

    food = copy.deepcopy(((public_state.get("assistantViews") or {}).get("food") or {}))
    food_records = list(food.pop("summary", []) or [])
    food.pop("cookingSummary", None)
    food_pages = _page_records(
        schema="pz-monitoring-bot/chatgpt-food-page/v1",
        snapshot=snapshot,
        records=food_records,
        instruction_ru=(
            "Группы еды с официальными названиями, свежестью, заморозкой, калориями, "
            "оставшейся долей, хранением и вариантами рецептов."
        ),
    )
    food_refs = []
    for index, payload in enumerate(food_pages, start=1):
        name = f"food-{index:03d}.json"
        files[name] = payload
        food_refs.append(f"live/chatgpt/{name}")
    files["food.json"] = {
        "schema": "pz-monitoring-bot/chatgpt-food-index/v1",
        "snapshot": snapshot,
        "instruction_ru": "Сводка еды и ссылки на все страницы foodPages.",
        **food,
        "foodGroupCount": len(food_records),
        "foodPages": food_refs,
    }

    changes = list(public_state.get("recentChanges") or [])
    change_pages = _page_records(
        schema="pz-monitoring-bot/chatgpt-changes-page/v1",
        snapshot=snapshot,
        records=changes,
        instruction_ru=(
            "События текущего экспорта. Одинаковый itemId в разных путях означает move, "
            "а не приход/расход."
        ),
    )
    change_refs = []
    for index, payload in enumerate(change_pages, start=1):
        name = f"changes-{index:03d}.json"
        files[name] = payload
        change_refs.append(f"live/chatgpt/{name}")
    files["changes.json"] = {
        "schema": "pz-monitoring-bot/chatgpt-changes-index/v1",
        "snapshot": snapshot,
        "instruction_ru": "Метаданные и страницы последних изменений.",
        "meta": copy.deepcopy(public_state.get("recentChangesMeta") or {}),
        "changePages": change_refs,
    }

    resources = copy.deepcopy(
        ((public_state.get("assistantViews") or {}).get("resources") or {})
    )
    resource_records = list(resources.pop("items", []) or [])
    resource_pages = _page_records(
        schema="pz-monitoring-bot/chatgpt-resources-page/v1",
        snapshot=snapshot,
        records=resource_records,
        instruction_ru=(
            "Полный каталог наших ресурсов, сгруппированный по name_ru/FullType. "
            "locations содержит количество и точное место каждой группы."
        ),
    )
    resource_refs = []
    for index, payload in enumerate(resource_pages, start=1):
        name = f"resources-{index:03d}.json"
        files[name] = payload
        resource_refs.append(f"live/chatgpt/{name}")
    files["resources.json"] = {
        "schema": "pz-monitoring-bot/chatgpt-resources-index/v1",
        "snapshot": snapshot,
        "instruction_ru": (
            "Для поиска предмета последовательно проверь resourcePages. Показывай name_ru, "
            "количество и понятное место; FullType оставляй техническим полем."
        ),
        **resources,
        "resourceGroupCount": len(resource_records),
        "resourcePages": resource_refs,
    }

    entries = []
    for name, payload in sorted(files.items()):
        content = _encoded(payload)
        entries.append(
            {
                "path": f"live/chatgpt/{name}",
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "withinConnectorLimit": len(content) <= MAX_CHATGPT_FILE_BYTES,
            }
        )

    manifest = {
        "schema": "pz-monitoring-bot/chatgpt-manifest/v1",
        "snapshot": snapshot,
        "instruction_ru": (
            "Это единственный индекс публичных данных. Все перечисленные файлы относятся "
            "к одному снимку; сначала открой overview.json, затем только нужные разделы."
        ),
        "maxFileBytes": MAX_CHATGPT_FILE_BYTES,
        "sectionPaths": section_paths,
        "files": entries,
    }
    manifest_bytes = _encoded(manifest)

    bootstrap = {
        "schema": "pz-monitoring-bot/chatgpt-state/v4",
        "schemaVersion": public_state.get("schemaVersion"),
        "instruction_ru": (
            "Этот файл теперь является небольшим загрузчиком. Не ищи здесь полный инвентарь. "
            "Открой manifestPath, затем overview.json и нужные тематические страницы."
        ),
        "status": copy.deepcopy(public_state.get("status") or {}),
        "updatedAt": public_state.get("updatedAt"),
        "game": copy.deepcopy(public_state.get("game") or {}),
        "save": copy.deepcopy(public_state.get("save") or {}),
        "overview": copy.deepcopy(public_state.get("overview") or {}),
        "manifestPath": "live/chatgpt/manifest.json",
        "manifestBytes": len(manifest_bytes),
        "sectionPaths": section_paths,
    }
    return files, manifest, bootstrap


def write_public_files(
    live_dir: Path,
    *,
    current_state: dict[str, Any],
    public_state: dict[str, Any],
) -> dict[str, Any]:
    files, manifest, bootstrap = build_public_files(current_state, public_state)
    target = live_dir / "chatgpt"
    target.mkdir(parents=True, exist_ok=True)
    desired = {"manifest.json", *files.keys()}
    for old_path in target.glob("*.json"):
        if old_path.name not in desired:
            old_path.unlink()
    for name, payload in files.items():
        atomic_write_json(target / name, payload, compact=True)
    atomic_write_json(target / "manifest.json", manifest, compact=True)
    return bootstrap
