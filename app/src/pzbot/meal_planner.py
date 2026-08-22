"""Deterministic Build 42 evolved-recipe planner.

The planner reads the installed game's generated item and evolved-recipe
scripts.  Inventory data decides what is owned; game scripts decide what can
actually be added to each dish.  No compatibility is inferred from names.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import json
import re
from pathlib import Path
from typing import Any, Iterable


_MODULE = re.compile(r"^\s*module\s+([^\s{]+)", re.I)
_BLOCK = re.compile(r"^\s*(item|evolvedrecipe)\s+(.+?)\s*$", re.I)
_PROPERTY = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.*?),?\s*$")
_DISPOSAL_WORDS = ("мусор", "компост", "trash", "garbage", "compost")


def _load_json(path: Path) -> dict[str, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _blocks(path: Path, kind: str) -> Iterable[tuple[str, str, list[str]]]:
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return
    module = "Base"
    index = 0
    while index < len(lines):
        module_match = _MODULE.match(lines[index])
        if module_match:
            module = module_match.group(1)
        match = _BLOCK.match(lines[index])
        if not match or match.group(1).casefold() != kind.casefold():
            index += 1
            continue
        identifier = match.group(2).strip()
        start = index
        while start < len(lines) and "{" not in lines[start]:
            start += 1
        if start >= len(lines):
            break
        body: list[str] = []
        depth = 0
        cursor = start
        while cursor < len(lines):
            line = lines[cursor]
            depth += line.count("{") - line.count("}")
            if cursor > start and depth > 0:
                body.append(line)
            if cursor > start and depth == 0:
                break
            cursor += 1
        yield module, identifier, body
        index = cursor + 1


def _properties(lines: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    depth = 0
    for line in lines:
        depth += line.count("{") - line.count("}")
        if depth:
            continue
        match = _PROPERTY.match(line)
        if match:
            result[match.group(1)] = match.group(2).strip()
    return result


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool:
    return str(value or "false").casefold() == "true"


def _parse_evolved_options(value: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw_option in str(value or "").split(";"):
        clean = raw_option.strip()
        if not clean:
            continue
        core, _, condition_text = clean.partition("|")
        recipe_name, separator, amount_text = core.rpartition(":")
        if not separator:
            recipe_name = core
            amount_text = "1"
        amount = _float(amount_text, 1.0)
        conditions = [part.strip() for part in condition_text.split("|") if part.strip()]
        result.append(
            {
                "template": recipe_name.strip(),
                "useHungerUnits": amount,
                "requiresCooked": any(value.casefold() == "cooked" for value in conditions),
                "conditions": conditions,
            }
        )
    return result


def load_evolved_catalog(game_path: Path) -> dict[str, Any]:
    generated = game_path / "media" / "scripts" / "generated"
    locale = game_path / "media" / "lua" / "shared" / "Translate" / "RU"
    item_names = _load_json(locale / "ItemName.json")
    evolved_names = _load_json(locale / "EvolvedRecipeName.json")
    recipe_names = _load_json(locale / "Recipes.json")

    ingredients: dict[str, dict[str, Any]] = {}
    item_files = sorted((generated / "items").glob("*.txt"))
    for path in item_files:
        for module, identifier, body in _blocks(path, "item"):
            props = _properties(body)
            if not props.get("EvolvedRecipe"):
                continue
            full_type = f"{module}.{identifier}"
            hunger_units = abs(_float(props.get("HungerChange")))
            ingredients[full_type] = {
                "fullType": full_type,
                "name_ru": item_names.get(full_type) or evolved_names.get(full_type) or identifier,
                "evolvedName_ru": evolved_names.get(full_type)
                or props.get("EvolvedRecipeName")
                or item_names.get(full_type)
                or identifier,
                "options": _parse_evolved_options(props.get("EvolvedRecipe") or ""),
                "spice": _bool(props.get("Spice")),
                "scriptNutrition": {
                    "hungerUnits": hunger_units,
                    "calories": _float(props.get("Calories")),
                    "carbohydrates": _float(props.get("Carbohydrates")),
                    "lipids": _float(props.get("Lipids")),
                    "proteins": _float(props.get("Proteins")),
                },
                "source": str(path.relative_to(game_path)).replace("\\", "/"),
            }

    definitions: list[dict[str, Any]] = []
    evolved_path = generated / "evolvedrecipes.txt"
    for module, identifier, body in _blocks(evolved_path, "evolvedrecipe"):
        props = _properties(body)
        max_items = _float(props.get("MaxItems"))
        minimum_water = _float(props.get("MinimumWater"))
        display_key = props.get("Name") or identifier
        definitions.append(
            {
                "recipeId": f"{module}.{identifier}",
                "internalName": identifier,
                "template": props.get("Template") or identifier,
                "name_ru": recipe_names.get(display_key) or display_key,
                "baseItem": props.get("BaseItem"),
                "baseItemName_ru": item_names.get(props.get("BaseItem") or "")
                or props.get("BaseItem"),
                "resultItem": props.get("ResultItem"),
                "resultName_ru": item_names.get(props.get("ResultItem") or "")
                or props.get("ResultItem"),
                "maxItems": int(max_items) if max_items else None,
                "minimumWater": minimum_water if minimum_water else None,
                "cookable": _bool(props.get("Cookable")),
                "source": str(evolved_path.relative_to(game_path)).replace("\\", "/"),
            }
        )
    return {
        "schema": "pz-monitoring-bot/evolved-catalog/v1",
        "source": "installed_game_generated_scripts",
        "itemFilesParsed": len(item_files),
        "ingredientDefinitions": ingredients,
        "dishDefinitions": definitions,
    }


def _is_disposal(item: dict[str, Any]) -> bool:
    source = item.get("source") or {}
    text = " ".join(
        str(source.get(key) or "")
        for key in ("containerDisplayName", "containerCustomName", "containerType", "path")
    ).casefold()
    return any(word in text for word in _DISPOSAL_WORDS)


def _location(item: dict[str, Any]) -> dict[str, Any]:
    source = item.get("source") or {}
    return {
        "container_ru": source.get("containerDisplayName") or "Инвентарь персонажа",
        "containerId": source.get("containerId"),
        "path": source.get("path"),
        "position": source.get("position"),
        "stale": bool(source.get("stale")),
    }


def _available_hunger_units(item: dict[str, Any], definition: dict[str, Any]) -> float:
    food = item.get("food") or {}
    runtime_units = abs(_float(food.get("hungerChange"))) * 100.0
    current_uses = _float(item.get("currentUses"))
    script_units = _float((definition.get("scriptNutrition") or {}).get("hungerUnits"))
    return max(runtime_units, current_uses, script_units if runtime_units <= 0 else 0.0, 1.0)


def _runtime_nutrition(item: dict[str, Any], definition: dict[str, Any]) -> dict[str, float]:
    food = item.get("food") or {}
    script = definition.get("scriptNutrition") or {}
    return {
        key: _float(food.get(key), _float(script.get(key)))
        for key in ("calories", "carbohydrates", "lipids", "proteins")
    }


def _serving_candidates(
    instances: list[dict[str, Any]],
    ingredient: dict[str, Any],
    option: dict[str, Any],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in instances:
        food = item.get("food") or {}
        if option.get("requiresCooked") and not food.get("cooked"):
            continue
        total_units = _available_hunger_units(item, ingredient)
        remaining = total_units
        nutrition = _runtime_nutrition(item, ingredient)
        index = 0
        while remaining > 0.001 and index < limit:
            used = min(_float(option.get("useHungerUnits"), 1.0), remaining)
            ratio = used / total_units if total_units else 0.0
            result.append(
                {
                    "candidateId": f"{item.get('itemId')}:{index}",
                    "itemId": item.get("itemId"),
                    "fullType": item.get("fullType"),
                    "name_ru": item.get("name_ru") or item.get("nameLocalized") or ingredient.get("name_ru"),
                    "evolvedName_ru": ingredient.get("evolvedName_ru"),
                    "useHungerUnits": round(used, 3),
                    "consumesWholeItem": used >= remaining - 0.001,
                    "requiresCooked": bool(option.get("requiresCooked")),
                    "spice": bool(ingredient.get("spice")),
                    "nutrition": {
                        key: round(value * ratio, 3) for key, value in nutrition.items()
                    },
                    "freshness": food.get("freshnessStage"),
                    "hoursUntilStaleAtRoomTemperature": food.get("hoursUntilStaleAtRoomTemperature"),
                    "frozen": bool(food.get("frozen")),
                    "location": _location(item),
                    "source": ingredient.get("source"),
                }
            )
            remaining -= used
            index += 1
    return result


def _nutrition(candidates: list[dict[str, Any]]) -> dict[str, float]:
    totals = {
        "hungerReduction": 0.0,
        "calories": 0.0,
        "carbohydrates": 0.0,
        "lipids": 0.0,
        "proteins": 0.0,
    }
    for candidate in candidates:
        totals["hungerReduction"] += _float(candidate.get("useHungerUnits"))
        values = candidate.get("nutrition") or {}
        for key in ("calories", "carbohydrates", "lipids", "proteins"):
            totals[key] += _float(values.get(key))
    return {key: round(value, 2) for key, value in totals.items()}


def _collapse(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        key = str(candidate.get("fullType"))
        row = grouped.setdefault(
            key,
            {
                "fullType": candidate.get("fullType"),
                "name_ru": candidate.get("name_ru"),
                "additions": 0,
                "useHungerUnits": 0.0,
                "nutrition": {"calories": 0.0, "carbohydrates": 0.0, "lipids": 0.0, "proteins": 0.0},
                "locations": [],
                "itemIds": [],
            },
        )
        row["additions"] += 1
        row["useHungerUnits"] += _float(candidate.get("useHungerUnits"))
        for field in row["nutrition"]:
            row["nutrition"][field] += _float((candidate.get("nutrition") or {}).get(field))
        if candidate.get("location") not in row["locations"]:
            row["locations"].append(candidate.get("location"))
        if candidate.get("itemId") not in row["itemIds"]:
            row["itemIds"].append(candidate.get("itemId"))
    result = []
    for row in grouped.values():
        row["useHungerUnits"] = round(row["useHungerUnits"], 3)
        row["nutrition"] = {key: round(value, 2) for key, value in row["nutrition"].items()}
        result.append(row)
    result.sort(key=lambda row: (-float((row.get("nutrition") or {}).get("calories") or 0), str(row.get("name_ru"))))
    return result


def _take_best(
    pool: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    key,
    predicate=lambda value: True,
) -> None:
    used = {value.get("candidateId") for value in selected}
    candidates = [value for value in pool if value.get("candidateId") not in used and predicate(value)]
    if candidates:
        selected.append(max(candidates, key=key))


def _balanced(main: list[dict[str, Any]], max_items: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    _take_best(
        main,
        selected,
        lambda value: _float((value.get("nutrition") or {}).get("proteins")),
        lambda value: _float((value.get("nutrition") or {}).get("proteins")) > 0,
    )
    _take_best(
        main,
        selected,
        lambda value: _float((value.get("nutrition") or {}).get("carbohydrates")),
        lambda value: _float((value.get("nutrition") or {}).get("carbohydrates")) > 0,
    )
    _take_best(
        main,
        selected,
        lambda value: _float((value.get("nutrition") or {}).get("lipids")),
        lambda value: _float((value.get("nutrition") or {}).get("lipids")) > 0,
    )
    counts = Counter(str(value.get("fullType")) for value in selected)
    remaining = sorted(
        (value for value in main if value.get("candidateId") not in {item.get("candidateId") for item in selected}),
        key=lambda value: (
            -_float((value.get("nutrition") or {}).get("calories")),
            _float(value.get("hoursUntilStaleAtRoomTemperature"), 1_000_000),
            str(value.get("name_ru")),
        ),
    )
    for value in remaining:
        if len(selected) >= max_items:
            break
        full_type = str(value.get("fullType"))
        if counts[full_type] >= 2:
            continue
        selected.append(value)
        counts[full_type] += 1
    if len(selected) < max_items:
        for value in remaining:
            if len(selected) >= max_items:
                break
            if value not in selected:
                selected.append(value)
    return selected[:max_items]


def _profile(
    definition: dict[str, Any],
    profile: str,
    mains: list[dict[str, Any]],
    spices: list[dict[str, Any]],
    bowl_count: int,
) -> dict[str, Any]:
    max_items = int(definition.get("maxItems") or 1)
    if profile == "maximum_calories":
        chosen = sorted(
            mains,
            key=lambda value: -_float((value.get("nutrition") or {}).get("calories")),
        )[:max_items]
    else:
        chosen = _balanced(mains, max_items)

    spice_by_type: dict[str, dict[str, Any]] = {}
    for spice in sorted(
        spices,
        key=lambda value: -(
            _float((value.get("nutrition") or {}).get("calories"))
            + 9.0 * _float((value.get("nutrition") or {}).get("lipids"))
        ),
    ):
        spice_by_type.setdefault(str(spice.get("fullType")), spice)
    recommended_spices = [
        value
        for value in spice_by_type.values()
        if _float((value.get("nutrition") or {}).get("calories")) > 0
        or _float((value.get("nutrition") or {}).get("lipids")) > 0
    ][:1]
    all_used = chosen + recommended_spices
    totals = _nutrition(all_used)
    portions = 4 if bowl_count >= 4 else 2 if bowl_count >= 2 else 1
    per_portion = {key: round(value / portions, 2) for key, value in totals.items()}
    ingredients = _collapse(chosen)
    selected_spices = _collapse(recommended_spices)

    steps = [
        f"Возьми «{definition.get('baseItemName_ru')}» из указанного контейнера.",
    ]
    if definition.get("minimumWater"):
        percent = round(float(definition["minimumWater"]) * 100)
        steps.append(f"Наполни ёмкость чистой водой минимум до {percent}%.")
    steps.append(f"Выбери действие «{definition.get('name_ru')}».")
    for row in ingredients:
        steps.append(f"Добавь «{row.get('name_ru')}» {row.get('additions')} раз(а).")
    for row in selected_spices:
        steps.append(f"Добавь как приправу «{row.get('name_ru')}» {row.get('additions')} раз(а).")
    steps.append("Порядок основных ингредиентов скриптом не ограничен; важны число добавлений и совместимость.")
    if definition.get("cookable"):
        steps.append("Поставь заполненную ёмкость на исправный источник тепла и готовь до состояния «Готово», не допуская подгорания.")
    if portions > 1:
        steps.append(f"После приготовления раздели блюдо на {portions} миски.")

    return {
        "planId": f"{definition.get('recipeId')}:{profile}",
        "profile": profile,
        "confidence": "exact_installed_build_compatibility",
        "recipeId": definition.get("recipeId"),
        "name_ru": definition.get("name_ru"),
        "baseItem": definition.get("baseItem"),
        "baseItemName_ru": definition.get("baseItemName_ru"),
        "resultItem": definition.get("resultItem"),
        "maxMainIngredientSlots": max_items,
        "mainSlotsUsed": len(chosen),
        "minimumWater": definition.get("minimumWater"),
        "ingredients": ingredients,
        "recommendedSpices": selected_spices,
        "projectedWholeDish": totals,
        "portioning": {
            "bowls": portions,
            "availableBowls": bowl_count,
            "projectedPerBowl": per_portion,
        },
        "steps_ru": steps,
        "calculationRule_ru": (
            "Совместимость и расход взяты из локальных EvolvedRecipe Build 42.20.3. "
            "Пищевая ценность рассчитана из фактических экземпляров до бонусов навыка готовки."
        ),
    }


def build_meal_plans(
    owned: list[dict[str, Any]],
    *,
    game_path: Path,
) -> dict[str, Any]:
    catalog = load_evolved_catalog(game_path)
    ingredient_definitions = catalog["ingredientDefinitions"]
    food_instances = [
        item
        for item in owned
        if item.get("itemType") == "food"
        and not bool((item.get("food") or {}).get("rotten"))
        and not _is_disposal(item)
    ]
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    owned_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in owned:
        owned_by_type[str(item.get("fullType"))].append(item)
    for item in food_instances:
        by_type[str(item.get("fullType"))].append(item)

    bowl_count = len(owned_by_type.get("Base.Bowl", [])) + len(owned_by_type.get("Base.ClayBowl", []))
    dish_options: list[dict[str, Any]] = []
    recommended: list[dict[str, Any]] = []
    for definition in catalog["dishDefinitions"]:
        template = str(definition.get("template") or "").casefold()
        base_items = owned_by_type.get(str(definition.get("baseItem")), [])
        mains: list[dict[str, Any]] = []
        spices: list[dict[str, Any]] = []
        compatible_rows: list[dict[str, Any]] = []
        for full_type, ingredient in ingredient_definitions.items():
            instances = by_type.get(full_type, [])
            if not instances:
                continue
            matching = [
                option
                for option in ingredient.get("options") or []
                if str(option.get("template") or "").casefold() == template
            ]
            if not matching:
                continue
            option = matching[0]
            candidates = _serving_candidates(
                instances,
                ingredient,
                option,
                limit=max(int(definition.get("maxItems") or 1), 1),
            )
            if ingredient.get("spice"):
                spices.extend(candidates)
            else:
                mains.extend(candidates)
            compatible_rows.append(
                {
                    "fullType": full_type,
                    "name_ru": instances[0].get("name_ru")
                    or instances[0].get("nameLocalized")
                    or ingredient.get("name_ru"),
                    "useHungerUnitsPerAddition": option.get("useHungerUnits"),
                    "requiresCooked": option.get("requiresCooked"),
                    "spice": bool(ingredient.get("spice")),
                    "availableInstances": len(instances),
                    "availableAdditions": len(candidates),
                    "locations": list({str(_location(item).get('container_ru')) for item in instances}),
                    "source": ingredient.get("source"),
                }
            )
        if not mains and not spices:
            continue
        option_row = {
            **definition,
            "baseItemAvailable": bool(base_items),
            "baseItemLocations": [_location(item) for item in base_items],
            "compatibleOwnedIngredients": sorted(
                compatible_rows,
                key=lambda row: (bool(row.get("spice")), str(row.get("name_ru"))),
            ),
            "mainIngredientKindsAvailable": len({value.get("fullType") for value in mains}),
            "mainIngredientAdditionsAvailable": len(mains),
            "spiceKindsAvailable": len({value.get("fullType") for value in spices}),
        }
        if base_items and mains:
            plans = [
                _profile(definition, "balanced_nutrition", mains, spices, bowl_count),
                _profile(definition, "maximum_calories", mains, spices, bowl_count),
            ]
            for plan in plans:
                plan["baseItemLocations"] = [_location(item) for item in base_items]
            option_row["plans"] = plans
            recommended.append(plans[0])
            recommended.append(plans[1])
        else:
            option_row["plans"] = []
        dish_options.append(option_row)

    recommended.sort(
        key=lambda plan: (
            0 if plan.get("profile") == "balanced_nutrition" else 1,
            -_float((plan.get("projectedWholeDish") or {}).get("calories")),
            str(plan.get("name_ru")),
        )
    )
    return {
        "schema": "pz-monitoring-bot/meal-plans/v1",
        "catalog": {
            "source": catalog.get("source"),
            "itemFilesParsed": catalog.get("itemFilesParsed"),
            "ingredientDefinitions": len(ingredient_definitions),
            "dishDefinitions": len(catalog.get("dishDefinitions") or []),
        },
        "dishOptions": dish_options,
        "recommendedPlans": recommended,
        "rule_ru": (
            "Планы строятся только по точным EvolvedRecipe установленного Build 42.20.3. "
            "Отсутствие продукта в текущем контекстном меню не считается несовместимостью."
        ),
    }
