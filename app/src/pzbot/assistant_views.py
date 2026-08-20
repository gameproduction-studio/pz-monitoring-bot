"""Small, explicit views that ordinary ChatGPT can analyze safely."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .spoilage import build_spoilage_alerts
from .state_diff import flatten_state


def _location(item: dict[str, Any]) -> dict[str, Any]:
    source = item.get("source") or {}
    label = source.get("containerDisplayName") or "Inventory of character"
    if source.get("scope") != "character" and not source.get("containerDisplayName"):
        label = source.get("containerDisplayName") or source.get("containerType") or "World container"
    return {
        "label": label,
        "path": source.get("path"),
        "containerId": source.get("containerId"),
        "position": source.get("position"),
        "owned": bool(source.get("owned")),
        "stale": bool(source.get("stale")),
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
            "ownedRule": "character inventory or container opened by player or inside base",
            "staleRule": (
                "stale=true means last known contents; do not claim they are still present "
                "without qualification."
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
        "search": {
            "coverageWarning": (
                "Only currently observed or last-known indexed items are searchable; "
                "unexplored locations are not guaranteed sources."
            ),
            "playerPosition": player_position,
            "items": search_index,
        },
        "ownedItemsByLocation": dict(sorted(by_location.items())),
    }
