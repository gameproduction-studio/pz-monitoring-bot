"""Small, explicit views that ordinary ChatGPT can analyze safely."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .spoilage import build_spoilage_alerts
from .state_diff import flatten_state


def _location(item: dict[str, Any]) -> dict[str, Any]:
    source = item.get("source") or {}
    label = source.get("containerDisplayName") or "Инвентарь персонажа"
    if source.get("scope") != "character" and not source.get("containerDisplayName"):
        label = source.get("containerDisplayName") or source.get("containerType") or "Контейнер мира"
    return {
        "label": label,
        "path": source.get("path"),
        "containerId": source.get("containerId"),
        "position": source.get("position"),
        "owned": bool(source.get("owned")),
        "stale": bool(source.get("stale")),
        "scope": source.get("scope"),
        "containerType": source.get("containerType"),
    }

def _direction(dx: float, dy: float) -> str:
    horizontal = "E" if dx > 0.5 else "W" if dx < -0.5 else ""
    vertical = "S" if dy > 0.5 else "N" if dy < -0.5 else ""
    return vertical + horizontal or "HERE"


def _search_record(
    item: dict[str, Any],
    player_position: dict[str, Any],
) -> dict[str, Any]:
    source = item.get("source") or {}
    position = source.get("position")
    if source.get("scope") == "character":
        position = player_position
    distance = None
    direction = None
    if position and player_position:
        dx = float(position.get("x", 0)) - float(player_position.get("x", 0))
        dy = float(position.get("y", 0)) - float(player_position.get("y", 0))
        dz = float(position.get("z", 0)) - float(player_position.get("z", 0))
        distance = round((dx * dx + dy * dy) ** 0.5, 2)
        direction = _direction(dx, dy)
        if abs(dz) > 0.01:
            direction += f" Z{dz:+g}"

    stale = bool(source.get("stale"))
    if source.get("scope") == "character":
        availability = "in_character_inventory"
    elif stale:
        availability = "last_known_stale"
    elif source.get("owned"):
        availability = "owned_storage"
    else:
        availability = "observed_world"

    portable = item.get("portableContainer") or {}
    location = _location(item)
    return {
        "itemId": item.get("itemId"),
        "fullType": item.get("fullType"),
        "name_ru": item.get("name_ru"),
        "tags": item.get("tags") or [],
        "category": item.get("category"),
        "condition": item.get("condition"),
        "conditionMax": item.get("conditionMax"),
        "isPortableContainer": bool(portable),
        "capacity": portable.get("capacity"),
        "weightReduction": portable.get("weightReduction"),
        "availability": availability,
        "distanceTiles": distance,
        "directionFromPlayer": direction,
        "location": location,
    }

def _parse_evolved_recipes(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, str) or not value.strip():
        return []
    result: list[dict[str, Any]] = []
    for raw in value.split(";"):
        raw = raw.strip()
        if not raw:
            continue
        definition, _, requirement = raw.partition("|")
        name, separator, amount_text = definition.rpartition(":")
        if not separator:
            name, amount_text = definition, ""
        try:
            amount = float(amount_text)
        except ValueError:
            amount = None
        result.append(
            {
                "recipeId": name.strip(),
                "ingredientAmount": amount,
                "requiresCookedIngredient": requirement.strip().lower() == "cooked",
            }
        )
    return result


def _food_record(item: dict[str, Any]) -> dict[str, Any]:
    food = item.get("food") or {}
    return {
        "itemId": item.get("itemId"),
        "fullType": item.get("fullType"),
        "name_ru": item.get("name_ru"),
        "caloriesReportedByGame": food.get("calories"),
        "carbohydrates": food.get("carbohydrates"),
        "lipids": food.get("lipids"),
        "proteins": food.get("proteins"),
        "hungerChange": food.get("hungerChange"),
        "remainingFraction": item.get("remainingFraction"),
        "currentUses": item.get("currentUses"),
        "freshness": food.get("freshnessStage"),
        "frozen": bool(food.get("frozen")),
        "freezingTime": food.get("freezingTime"),
        "cooked": bool(food.get("cooked")),
        "burnt": bool(food.get("burnt")),
        "recipeOptions": _parse_evolved_recipes(food.get("evolvedRecipeName")),
        "rotten": bool(food.get("rotten")),
        "cookable": bool(food.get("cookable")),
        "dangerousUncooked": bool(food.get("dangerousUncooked")),
        "foodType": food.get("foodType"),
        "evolvedRecipeName": food.get("evolvedRecipeName"),
        "replaceOnCooked": food.get("replaceOnCooked") or [],
        "hoursUntilStaleAtRoomTemperature": food.get(
            "hoursUntilStaleAtRoomTemperature"
        ),
        "hoursUntilRottenAtRoomTemperature": food.get(
            "hoursUntilRottenAtRoomTemperature"
        ),
        "location": _location(item),
    }


def _vehicle_record(
    vehicle: dict[str, Any],
    current_world_age_hours: Any,
) -> dict[str, Any]:
    observation = vehicle.get("observation") or {}
    stale = bool(observation.get("stale"))
    last_seen = observation.get("lastSeenWorldAgeHours")
    hours_since_last_seen = (
        round(max(0.0, float(current_world_age_hours) - float(last_seen)), 2)
        if isinstance(current_world_age_hours, (int, float))
        and isinstance(last_seen, (int, float))
        else None
    )
    fuel = vehicle.get("fuel") or {}
    fraction = fuel.get("fraction")
    fuel_percent = round(float(fraction) * 100.0, 1) if fraction is not None else None
    alerts: list[dict[str, Any]] = []
    if fuel_percent is not None and fuel_percent <= 25:
        alerts.append(
            {
                "kind": "vehicle_low_fuel",
                "severity": "critical" if fuel_percent <= 10 else "warning",
                "fuelPercent": fuel_percent,
                "message_ru": (
                    f"В автомобиле «{vehicle.get('name')}» осталось {fuel_percent:g}% топлива. "
                    "Заправь его перед дальней дорогой."
                ),
            }
        )
    battery = vehicle.get("batteryCharge")
    if isinstance(battery, (int, float)) and float(battery) <= 0.25:
        alerts.append(
            {
                "kind": "vehicle_low_battery",
                "severity": "warning",
                "chargePercent": round(float(battery) * 100.0, 1),
                "message_ru": f"У автомобиля «{vehicle.get('name')}» низкий заряд аккумулятора.",
            }
        )
    weak_parts = []
    for part in vehicle.get("parts") or []:
        condition = part.get("condition")
        if isinstance(condition, (int, float)) and float(condition) < 40:
            weak_parts.append(
                {
                    "partId": part.get("partId"),
                    "name_ru": part.get("nameLocalized"),
                    "conditionPercent": condition,
                    "installed": part.get("installed"),
                }
            )
    if weak_parts:
        alerts.append(
            {
                "kind": "vehicle_weak_parts",
                "severity": "critical" if any(float(p["conditionPercent"]) < 20 for p in weak_parts) else "warning",
                "parts": weak_parts,
                "message_ru": f"Автомобиль «{vehicle.get('name')}» имеет детали в плохом состоянии.",
            }
        )
    cargo = []
    for container in vehicle.get("containers") or []:
        cargo.append(
            {
                "containerId": container.get("containerId"),
                "name_ru": container.get("displayName"),
                "capacity": container.get("capacity"),
                "itemInstances": len(container.get("items") or []),
                "stale": bool((container.get("observation") or {}).get("stale")),
                "loadedNow": not bool((container.get("observation") or {}).get("stale")),
            }
        )
    return {
        "vehicleId": vehicle.get("vehicleId"),
        "keyId": vehicle.get("keyId"),
        "name": vehicle.get("name"),
        "displayName": vehicle.get("displayName"),
        "scriptFullType": vehicle.get("scriptFullType"),
        "position": vehicle.get("position"),
        "stale": stale,
        "loadedNow": not stale,
        "stateStatus": "live_loaded" if not stale else "last_confirmed_stable_while_unloaded",
        "stateRule_ru": (
            "В одиночной игре сохранённые топливо, детали и груз считаются действующим "
            "последним подтверждённым состоянием, пока автомобиль выгружен движком. "
            "Временные показатели уточняются при следующей загрузке автомобиля."
        ),
        "lastSeenAtWorldAgeHours": last_seen,        "hoursSinceLastSeen": hours_since_last_seen,
        "fuel": {
            "amount": fuel.get("amount"),
            "capacity": fuel.get("capacity"),
            "percent": fuel_percent,
        },
        "batteryChargePercent": round(float(battery) * 100.0, 1)
        if isinstance(battery, (int, float)) else None,
        "overallConditionPercent": vehicle.get("overallCondition"),
        "engine": vehicle.get("engine") or {},
        "parts": vehicle.get("parts") or [],
        "cargoContainers": cargo,
        "alerts": alerts,
    }

def build_assistant_views(snapshot: dict[str, Any]) -> dict[str, Any]:
    instances = list(flatten_state(snapshot).values())
    owned = [
        item for item in instances if bool((item.get("source") or {}).get("owned"))
    ]
    observed = [
        item for item in instances if not bool((item.get("source") or {}).get("owned"))
    ]
    player_position = (snapshot.get("character") or {}).get("position") or {}
    search_index = [_search_record(item, player_position) for item in instances]
    search_index.sort(
        key=lambda item: (
            item["distanceTiles"] is None,
            item["distanceTiles"] if item["distanceTiles"] is not None else float("inf"),
            str(item.get("name_ru")),
            str(item.get("itemId")),
        )
    )
    foods = [_food_record(item) for item in owned if item.get("itemType") == "food"]
    observed_foods = [
        _food_record(item) for item in observed if item.get("itemType") == "food"
    ]
    foods.sort(
        key=lambda item: (
            -(float(item.get("caloriesReportedByGame") or 0)),
            str(item.get("name_ru")),
            str(item.get("itemId")),
        )
    )

    by_location: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in owned:
        location = _location(item)
        by_location[str(location["label"])].append(
            {
                "itemId": item.get("itemId"),
                "fullType": item.get("fullType"),
                "name_ru": item.get("name_ru"),
                "condition": item.get("condition"),
                "conditionMax": item.get("conditionMax"),
                "path": location["path"],
            }
        )

    current_world_age_hours = (snapshot.get("game") or {}).get("worldAgeHours")
    vehicle_records = [
        _vehicle_record(vehicle, current_world_age_hours)
        for vehicle in (snapshot.get("world") or {}).get("vehicles") or []
    ]
    vehicle_alerts = [
        alert for vehicle in vehicle_records for alert in vehicle.get("alerts") or []
    ]

    cooking_candidates = [
        food
        for food in foods
        if food.get("cookable")
        or food.get("evolvedRecipeName")
        or food.get("replaceOnCooked")
    ]
    return {
        "contract": {
            "facts": (
                "All item values originate from the running game. Russian names are "
                "the installed game's active localization, not model translations."
            ),
            "ownedRule": (
                "character inventory, stationary container inside a saved base, "
                "or cargo of a registered vehicle; external world containers are excluded"
            ),
            "staleRule": (
                "For a registered vehicle in single-player, stale=true means not loaded by "
                "the engine now, not missing. Fuel, parts, and cargo remain the last confirmed "
                "state; only time-dependent values need refresh."
            ),            "presentationRule": (
                "Use Russian name_ru in user-facing answers. Never list itemId or fullType "
                "unless the user explicitly asks for technical identifiers."
            ),
            "recipeRule": (
                "cookingCandidates prove cookability only. Exact multi-ingredient recipes "
                "require recipe_catalog.json; never invent a recipe from this list."
            ),
        },
        "ownedItemCount": len(owned),
        "observedOnlyItemCount": len(observed),
        "ownedCountsByFullType": dict(
            sorted(Counter(str(item.get("fullType")) for item in owned).items())
        ),
        "food": {
            "owned": foods,
            "observedOnly": observed_foods,
            "totalCaloriesReportedByGame": round(
                sum(float(food.get("caloriesReportedByGame") or 0) for food in foods),
                2,
            ),
            "highCalorieOwned": foods[:10],
            "cookingCandidates": cooking_candidates,
            "spoilageAlerts": build_spoilage_alerts(owned),
        },
        "vehicles": {
            "owned": vehicle_records,
            "alerts": vehicle_alerts,
            "staleRule": (
                "A registered unloaded vehicle remains visible with its last confirmed fuel, "
                "parts, and cargo. Treat only time-dependent values as needing refresh."
            ),
        },
        "search": {
            "coverageWarning": (
                "Search covers the character, saved-base containers, and registered "
                "vehicles only. External world containers require an explicit future scan."
            ),
            "playerPosition": player_position,
            "items": search_index,
        },
        "ownedItemsByLocation": dict(sorted(by_location.items())),
    }
