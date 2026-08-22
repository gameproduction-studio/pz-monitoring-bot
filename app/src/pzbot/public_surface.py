"""Connector-safe, paged public telemetry for ordinary ChatGPT sessions."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .jsonio import atomic_write_json


MAX_CHATGPT_FILE_BYTES = 32_000


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



def _human_path(value: Any) -> str:
    return re.sub(r" #\d+", "", str(value or "Неизвестное место"))


def _quantity(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _character_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        full_type = str(row.get("fullType") or "")
        name = str(row.get("name_ru") or row.get("nameLocalized") or full_type)
        key = (name, full_type)
        entry = grouped.setdefault(
            key,
            {
                "name_ru": name,
                "quantity": 0,
                "locations": {},
                "equipped": False,
                "primaryHand": False,
                "secondaryHand": False,
                "conditionPercents": [],
                "fullType": full_type,
            },
        )
        quantity = _quantity(row.get("quantity")) or 1
        entry["quantity"] += quantity
        human_path = _human_path(row.get("containerPath_ru"))
        entry["locations"][human_path] = entry["locations"].get(human_path, 0) + quantity
        entry["equipped"] = entry["equipped"] or bool(row.get("equipped"))
        entry["primaryHand"] = entry["primaryHand"] or bool(row.get("primaryHand"))
        entry["secondaryHand"] = entry["secondaryHand"] or bool(row.get("secondaryHand"))
        condition = row.get("condition")
        condition_max = row.get("conditionMax")
        if isinstance(condition, (int, float)) and isinstance(condition_max, (int, float)) and condition_max:
            entry["conditionPercents"].append(round(condition / condition_max * 100, 1))

    result = []
    for entry in grouped.values():
        conditions = entry.pop("conditionPercents")
        locations = entry.pop("locations")
        entry["locations_ru"] = [
            {"name_ru": name, "quantity": quantity}
            for name, quantity in sorted(locations.items())
        ]
        if conditions:
            entry["conditionPercentMin"] = min(conditions)
            entry["conditionPercentMax"] = max(conditions)
        result.append(entry)
    return sorted(
        result,
        key=lambda row: (str(row.get("name_ru") or "").casefold(), row.get("fullType") or ""),
    )


_DISPOSAL_TYPES = {"bin", "trash", "trashcan", "garbage", "garbagecan", "composter"}
_DISPOSAL_WORDS = ("мусор", "компост", "trash", "garbage", "compost")


def _is_disposal_location(location: dict[str, Any] | None) -> bool:
    location = location or {}
    storage_type = str(location.get("storageType") or "").casefold()
    if storage_type in _DISPOSAL_TYPES:
        return True
    location_text = " ".join(
        str(location.get(key) or "")
        for key in ("name_ru", "containerId", "label", "path")
    ).casefold()
    return any(word in location_text for word in _DISPOSAL_WORDS)


def _is_actionable_spoilage_alert(alert: dict[str, Any]) -> bool:
    if str(alert.get("severity") or "").casefold() != "low":
        return True
    hours_to_stale = alert.get("estimatedGameHoursToStale")
    hours_to_rotten = alert.get("estimatedGameHoursToRotten")
    if not isinstance(hours_to_stale, (int, float)):
        return True
    return hours_to_stale <= 72 or (
        isinstance(hours_to_rotten, (int, float)) and hours_to_rotten <= 120
    )


def _enrich_food_record(record: dict[str, Any]) -> dict[str, Any]:
    row = copy.deepcopy(record)
    location = row.get("location") or {}
    freshness = str(row.get("freshness") or "unknown").casefold()
    storage_type = str(location.get("storageType") or "").casefold()
    disposal = _is_disposal_location(location)
    rotten = bool(row.get("rotten")) or freshness == "rotten"

    row["freshness_ru"] = {
        "fresh": "Свежий",
        "stale": "Залежавшийся",
        "rotten": "Испорченный",
    }.get(freshness, "Состояние не определено")
    row["edibleStatus"] = (
        "waste" if rotten else "edible_with_penalty" if freshness == "stale" else "edible"
    )
    row["edibleStatus_ru"] = {
        "waste": "Не для еды: отходы/компост",
        "edible_with_penalty": "Съедобный, но снижает настроение и повышает скуку",
        "edible": "Съедобный",
    }[row["edibleStatus"]]
    row["storageIntent"] = "compost_or_disposal" if disposal else "food_storage"
    row["excludeFromEdibleStock"] = disposal or rotten
    row["attentionRequired"] = (
        not disposal and not rotten and storage_type not in {"freezer", "fridge", "refrigerator"}
    )

    if disposal:
        preservation = "compost_or_disposal"
    elif storage_type == "freezer":
        preservation = "frozen" if row.get("frozen") else "freezing_in_freezer"
    elif storage_type in {"fridge", "refrigerator"}:
        preservation = "refrigerated"
    elif row.get("frozen") or (row.get("freezingTime") or 0) > 0:
        preservation = "thawing_outside_freezer"
    else:
        preservation = "room_temperature"
    row["preservationState"] = preservation
    row["protectedByColdStorage"] = storage_type in {"freezer", "fridge", "refrigerator"}
    return row


def _resource_summary(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        locations = []
        by_scope: dict[str, int] = {}
        for location in record.get("locations") or []:
            quantity = _quantity(location.get("quantity"))
            scope = str(location.get("scope") or "unknown")
            by_scope[scope] = by_scope.get(scope, 0) + quantity
            location_name = location.get("name_ru") or "Неизвестное место"
            locations.append(f"{location_name} ×{quantity}")
        rows.append(
            {
                "name_ru": record.get("name_ru") or record.get("fullType"),
                "quantity": _quantity(record.get("quantity")),
                "onCharacter": _quantity(record.get("onCharacter")),
                "inBases": by_scope.get("world", 0),
                "inVehicles": by_scope.get("vehicle", 0),
                "locations": locations,
                "conditionPercentMin": record.get("conditionPercentMin"),
                "conditionPercentMax": record.get("conditionPercentMax"),
                "fullType": record.get("fullType"),
            }
        )
    return sorted(
        rows,
        key=lambda row: (str(row.get("name_ru") or "").casefold(), row.get("fullType") or ""),
    )


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
        "calculations": "live/chatgpt/calculations.json",
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
    character_summary = _character_summary(character_rows)
    files["character.json"] = {
        "schema": "pz-monitoring-bot/chatgpt-character/v2",
        "snapshot": snapshot,
        "instruction_ru": (
            "inventorySummary уже содержит полный компактный перечень вещей персонажа. "
            "Показывай таблицу: предмет, количество, где лежит, экипирован/в руках. "
            "inventoryPages открывай только для itemId и точных свойств экземпляров."
        ),
        "character": character,
        "inventoryItemGroups": len(character_rows),
        "inventorySummaryCount": len(character_summary),
        "duplicateItemKinds": sum(1 for row in character_summary if row["quantity"] > 1),
        "inventorySummary": character_summary,
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
    food_records = [
        _enrich_food_record(record)
        for record in list(food.pop("summary", []) or [])
    ]
    food.pop("cookingSummary", None)
    food["highCalorieSummary"] = [
        _enrich_food_record(record)
        for record in list(food.get("highCalorieSummary") or [])
        if not _is_disposal_location(record.get("location"))
        and not record.get("rotten")
        and str(record.get("freshness") or "").casefold() != "rotten"
    ]
    disposal_container_ids = {
        str((record.get("location") or {}).get("containerId"))
        for record in food_records
        if record.get("storageIntent") == "compost_or_disposal"
    }
    raw_alerts = list(food.get("spoilageAlerts") or [])
    non_disposal_alerts = [
        alert
        for alert in raw_alerts
        if not any(container_id and container_id in str(alert.get("location") or "")
                   for container_id in disposal_container_ids)
    ]
    food["spoilageAlerts"] = [
        alert for alert in non_disposal_alerts if _is_actionable_spoilage_alert(alert)
    ]
    disposal_records = [
        record for record in food_records
        if record.get("storageIntent") == "compost_or_disposal"
    ]
    edible_records = [record for record in food_records if not record.get("excludeFromEdibleStock")]
    food["foodSemantics"] = {
        "fresh": "Свежий",
        "stale": "Залежавшийся: съедобен, но снижает настроение и повышает скуку",
        "rotten": "Испорченный: не учитывать как еду",
        "freezer": "Еда в морозильнике защищена: уже заморожена или замерзает",
        "disposal": "Еда в мусорке/компостной таре намеренно исключена из съедобных запасов",
    }
    food["edibleStock"] = {
        "groups": len(edible_records),
        "items": sum(_quantity(record.get("quantity")) for record in edible_records),
        "caloriesReportedByGame": round(sum(float(record.get("caloriesTotalReportedByGame") or 0) for record in edible_records), 2),
    }
    food["compostOrDisposal"] = {
        "groups": len(disposal_records),
        "items": sum(_quantity(record.get("quantity")) for record in disposal_records),
        "records": [
            {
                "name_ru": record.get("name_ru"),
                "quantity": record.get("quantity"),
                "freshness_ru": record.get("freshness_ru"),
                "location": record.get("location"),
                "fullType": record.get("fullType"),
            }
            for record in disposal_records
        ],
    }
    food["suppressedDisposalAlerts"] = len(raw_alerts) - len(non_disposal_alerts)
    food["deferredLowPriorityAlerts"] = len(non_disposal_alerts) - len(food["spoilageAlerts"])
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
    food_summary_fields = [
        "name_ru", "quantity", "freshness_ru", "edibleStatus",
        "preservationState", "calories", "location_ru", "fullType",
    ]
    food_summary_rows = [
        [
            record.get("name_ru"),
            record.get("quantity"),
            record.get("freshness_ru"),
            record.get("edibleStatus"),
            record.get("preservationState"),
            record.get("caloriesTotalReportedByGame"),
            (record.get("location") or {}).get("name_ru"),
            record.get("fullType"),
        ]
        for record in food_records
    ]
    food["highCalorieSummary"] = [
        {
            "name_ru": record.get("name_ru"),
            "quantity": record.get("quantity"),
            "calories": record.get("caloriesTotalReportedByGame"),
            "freshness_ru": record.get("freshness_ru"),
            "preservationState": record.get("preservationState"),
            "location_ru": (record.get("location") or {}).get("name_ru"),
            "fullType": record.get("fullType"),
        }
        for record in food["highCalorieSummary"]
    ]
    files["food.json"] = {
        "schema": "pz-monitoring-bot/chatgpt-food-index/v2",
        "snapshot": snapshot,
        "instruction_ru": (
            "Сначала используй edibleStock, highCalorieSummary и spoilageAlerts. "
            "compostOrDisposal — намеренно отложенные отходы: не советуй их есть, "
            "охлаждать или спасать. В морозильнике еда защищена, даже если ещё замерзает."
        ),
        **food,
        "foodGroupCount": len(food_records),
        "foodSummaryFields": food_summary_fields,
        "foodSummaryRows": food_summary_rows,
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
    resource_summary = _resource_summary(resource_records)
    resource_summary_pages = _page_records(
        schema="pz-monitoring-bot/chatgpt-resource-summary-page/v1",
        snapshot=snapshot,
        records=resource_summary,
        instruction_ru=(
            "Компактная полная сводка ресурсов. Для таблицы показывай name_ru, quantity "
            "и locations; FullType оставляй техническим полем."
        ),
    )
    resource_summary_refs = []
    for index, payload in enumerate(resource_summary_pages, start=1):
        name = f"resource-summary-{index:03d}.json"
        files[name] = payload
        resource_summary_refs.append(f"live/chatgpt/{name}")

    files["resources.json"] = {
        "schema": "pz-monitoring-bot/chatgpt-resources-index/v3",
        "snapshot": snapshot,
        "instruction_ru": (
            "summaryPages — полный компактный учёт: название, количество и места. "
            "Для обзора прочитай их и выведи короткую таблицу. duplicateItems помогает "
            "найти копии. resourcePages открывай только для itemId и точного поиска. "
            "FullType не показывай вместо русского названия."
        ),
        **resources,
        "resourceGroupCount": len(resource_records),
        "duplicateGroupCount": sum(1 for row in resource_summary if row["quantity"] > 1),
        "summaryPages": resource_summary_refs,
        "duplicateItems": [
            {"name_ru": row["name_ru"], "quantity": row["quantity"], "fullType": row["fullType"]}
            for row in resource_summary
            if row["quantity"] > 1
        ],
        "resourcePages": resource_refs,
    }

    calculations = copy.deepcopy(current_state.get("supplyCalculations") or {})
    calculation_status = copy.deepcopy((public_state.get("status") or {}).get("calculations") or {})
    calculation_inventory = calculations.get("inventory") or {}
    duplicate_groups = list(calculation_inventory.pop("duplicateGroups", []) or [])
    calculation_food = calculations.get("food") or {}
    high_calorie_items = list(calculation_food.pop("highCalorieItems", []) or [])
    disposal_items = list(calculation_food.pop("compostOrDisposalItems", []) or [])
    calculation_recipes = calculations.get("recipes") or {}
    craftable_recipes = list(calculation_recipes.pop("craftableNowExact", []) or [])
    nearly_craftable = list(calculation_recipes.pop("nearlyCraftable", []) or [])
    all_cooking_recipes = list(calculation_recipes.pop("allCookingRecipes", []) or [])
    evolved_dishes = list(calculation_recipes.pop("evolvedDishOptions", []) or [])

    calculation_page_specs = [
        ("calculation-duplicates", "pz-monitoring-bot/calculation-duplicates/v1", duplicate_groups,
         "Повторяющиеся ресурсы: официальное русское название и точное количество."),
        ("calculation-food", "pz-monitoring-bot/calculation-food/v1", high_calorie_items,
         "Съедобные продукты по убыванию известных игровых калорий."),
        ("calculation-disposal", "pz-monitoring-bot/calculation-disposal/v1", disposal_items,
         "Отходы и компост: не предлагай их есть или спасать."),
        ("calculation-craftable", "pz-monitoring-bot/calculation-craftable/v1", craftable_recipes,
         "Рецепты, для которых программа точно видит все явно описанные входы."),
        ("calculation-near", "pz-monitoring-bot/calculation-near/v1", nearly_craftable,
         "Почти доступные рецепты и недостающие группы ингредиентов."),
        ("calculation-recipes", "pz-monitoring-bot/calculation-recipes/v1", all_cooking_recipes,
         "Полный проверенный каталог рецептов готовки из установленного билда."),
        ("calculation-evolved", "pz-monitoring-bot/calculation-evolved/v1", evolved_dishes,
         "Составные блюда и доступные высококалорийные ингредиенты."),
    ]
    calculation_refs: dict[str, list[str]] = {}
    for prefix, schema, records, instruction in calculation_page_specs:
        refs = []
        pages = _page_records(
            schema=schema,
            snapshot=snapshot,
            records=records,
            instruction_ru=instruction,
        )
        for index, payload in enumerate(pages, start=1):
            name = f"{prefix}-{index:03d}.json"
            files[name] = payload
            refs.append(f"live/chatgpt/{name}")
        calculation_refs[prefix] = refs

    files["calculations.json"] = {
        "schema": "pz-monitoring-bot/chatgpt-calculations/v1",
        "snapshot": snapshot,
        "instruction_ru": (
            "Это результаты команды «Сделать расчёты». Используй их только когда "
            "status.ready=true и status.currentForSnapshot=true. Для вопроса о максимально "
            "калорийном блюде сначала открой evolvedDishPages и craftableRecipePages; "
            "не выдавай сумму ингредиентов за точную калорийность готовой порции."
        ),
        "status": calculation_status,
        "createdAt": calculations.get("createdAt"),
        "requestId": calculations.get("requestId"),
        "saveId": calculations.get("saveId"),
        "snapshotSequence": calculations.get("snapshotSequence"),
        "game": calculations.get("game") or {},
        "inventory": calculation_inventory,
        "food": calculation_food,
        "recipes": calculation_recipes,
        "duplicatePages": calculation_refs["calculation-duplicates"],
        "highCalorieFoodPages": calculation_refs["calculation-food"],
        "disposalPages": calculation_refs["calculation-disposal"],
        "craftableRecipePages": calculation_refs["calculation-craftable"],
        "nearlyCraftablePages": calculation_refs["calculation-near"],
        "allCookingRecipePages": calculation_refs["calculation-recipes"],
        "evolvedDishPages": calculation_refs["calculation-evolved"],
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
