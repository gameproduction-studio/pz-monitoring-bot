"""Offline supply calculations and Build 42.20 recipe matching.

This module never runs inside Project Zomboid.  It consumes one already-written
inventory snapshot, reads the installed game's generated scripts and official
Russian localization, and produces a compact decision surface for ChatGPT.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import json
import re
from pathlib import Path
from typing import Any, Iterable

from .state_diff import flatten_state


_DISPOSAL_WORDS = ("мусор", "компост", "trash", "garbage", "compost")
_BLOCK_START = re.compile(r"^\s*(craftRecipe|evolvedrecipe)\s+(.+?)\s*$", re.I)
_MODULE = re.compile(r"^\s*module\s+([^\s{]+)", re.I)
_PROPERTY = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.*?),?\s*$")
_ITEM_LINE = re.compile(r"^item\s+([0-9.]+)\s+(.+?)(?:,)?$", re.I)


def _load_json(path: Path) -> dict[str, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(key): str(item) for key, item in value.items()} if isinstance(value, dict) else {}


def _blocks(path: Path, kind: str) -> Iterable[tuple[str, str, list[str]]]:
    """Yield (module, id, body-lines) from generated script blocks."""
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
        match = _BLOCK_START.match(lines[index])
        if not match or match.group(1).casefold() != kind.casefold():
            index += 1
            continue
        identifier = match.group(2).strip()
        start = index
        while start < len(lines) and "{" not in lines[start]:
            start += 1
        if start >= len(lines):
            break
        depth = 0
        body: list[str] = []
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


def _subblock(lines: list[str], name: str) -> list[str]:
    for index, line in enumerate(lines):
        if line.strip().casefold() != name.casefold():
            continue
        cursor = index + 1
        while cursor < len(lines) and "{" not in lines[cursor]:
            cursor += 1
        if cursor >= len(lines):
            return []
        depth = 0
        result: list[str] = []
        while cursor < len(lines):
            current = lines[cursor]
            depth += current.count("{") - current.count("}")
            if depth > 0 and "{" not in current:
                result.append(current.strip())
            if depth == 0:
                return result
            cursor += 1
    return []


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


def _number(value: str) -> float:
    number = float(value)
    return int(number) if number.is_integer() else number


def _parse_item_line(line: str) -> dict[str, Any]:
    clean = line.strip().rstrip(",")
    match = _ITEM_LINE.match(clean)
    if not match:
        return {"kind": "unsupported", "raw": clean}
    amount = _number(match.group(1))
    rest = match.group(2)
    types_match = re.search(r"\[([^\]]+)\]", rest)
    tags_match = re.search(r"tags\[([^\]]+)\]", rest, re.I)
    mapper_match = re.search(r"mapper:([^\s,]+)", rest, re.I)
    if tags_match:
        alternatives = [value.strip() for value in tags_match.group(1).split(";") if value.strip()]
        match_kind = "tags"
    elif types_match:
        alternatives = [value.strip() for value in types_match.group(1).split(";") if value.strip()]
        match_kind = "fullTypes"
    else:
        token = rest.split()[0].rstrip(",") if rest.split() else ""
        alternatives = [token] if token and not token.startswith("mapper:") else []
        match_kind = "fullTypes" if alternatives else "mapper"
    return {
        "kind": "item",
        "amount": amount,
        "matchKind": match_kind,
        "alternatives": alternatives,
        "keep": bool(re.search(r"mode:keep\b", rest, re.I)),
        "destroy": bool(re.search(r"mode:destroy\b", rest, re.I)),
        "mapper": mapper_match.group(1) if mapper_match else None,
        "raw": clean,
    }


def _parse_io(lines: list[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for line in lines:
        clean = line.strip().rstrip(",")
        if not clean:
            continue
        if clean.casefold().startswith("item "):
            result.append(_parse_item_line(clean))
        elif clean.casefold().startswith(("fluid ", "-fluid ")):
            result.append({"kind": "fluid", "raw": clean})
        else:
            result.append({"kind": "unsupported", "raw": clean})
    return result


def load_recipe_catalog(game_path: Path) -> dict[str, Any]:
    scripts = game_path / "media" / "scripts" / "generated"
    locale = game_path / "media" / "lua" / "shared" / "Translate" / "RU"
    recipe_names = _load_json(locale / "Recipes.json")
    evolved_names = _load_json(locale / "EvolvedRecipeName.json")
    item_names = _load_json(locale / "ItemName.json")
    recipes: list[dict[str, Any]] = []
    source_files = sorted((scripts / "recipes").glob("*.txt"))
    for path in source_files:
        for module, identifier, body in _blocks(path, "craftRecipe"):
            props = _properties(body)
            category = props.get("category") or "Other"
            if category.casefold() != "cooking":
                continue
            display_key = props.get("Name") or identifier
            recipes.append(
                {
                    "recipeId": f"{module}.{identifier}",
                    "internalName": identifier,
                    "name_ru": recipe_names.get(identifier) or recipe_names.get(display_key) or display_key,
                    "category": category,
                    "inputs": _parse_io(_subblock(body, "inputs")),
                    "outputs": _parse_io(_subblock(body, "outputs")),
                    "needToBeLearned": str(props.get("NeedToBeLearn") or "false").casefold() == "true",
                    "source": str(path.relative_to(game_path)).replace("\\", "/"),
                }
            )
    evolved: dict[str, dict[str, Any]] = {}
    evolved_path = scripts / "evolvedrecipes.txt"
    for module, identifier, body in _blocks(evolved_path, "evolvedrecipe"):
        props = _properties(body)
        full_id = f"{module}.{identifier}"
        max_items = props.get("MaxItems")
        evolved[identifier] = {
            "recipeId": full_id,
            "internalName": identifier,
            "name_ru": recipe_names.get(props.get("Name") or "") or identifier,
            "baseItem": props.get("BaseItem"),
            "resultItem": props.get("ResultItem"),
            "resultName_ru": item_names.get(props.get("ResultItem") or ""),
            "maxItems": int(float(max_items)) if max_items else None,
            "cookable": str(props.get("Cookable") or "false").casefold() == "true",
            "source": str(evolved_path.relative_to(game_path)).replace("\\", "/"),
        }
    return {
        "source": "installed_game_files",
        "recipeFilesParsed": len(source_files) + (1 if evolved_path.is_file() else 0),
        "recipes": recipes,
        "evolvedRecipes": evolved,
        "recipeTranslations": len(recipe_names),
        "itemTranslations": len(item_names),
        "itemNames": item_names,
        "evolvedNames": evolved_names,
    }


def _is_disposal(item: dict[str, Any]) -> bool:
    source = item.get("source") or {}
    text = " ".join(
        str(source.get(key) or "")
        for key in ("containerDisplayName", "containerCustomName", "containerType", "path")
    ).casefold()
    return any(word in text for word in _DISPOSAL_WORDS)


def _availability(instances: list[dict[str, Any]]) -> tuple[Counter[str], Counter[str], dict[str, str]]:
    types: Counter[str] = Counter()
    tags: Counter[str] = Counter()
    names: dict[str, str] = {}
    for item in instances:
        full_type = str(item.get("fullType") or "")
        amount = item.get("currentUses")
        units = float(amount) if isinstance(amount, (int, float)) and amount > 1 else 1.0
        types[full_type] += units
        names.setdefault(full_type, str(item.get("name_ru") or item.get("nameLocalized") or full_type))
        for tag in item.get("tags") or []:
            tags[str(tag)] += units
    return types, tags, names


def _localized_alternatives(values: list[str], names: dict[str, str], catalog_names: dict[str, str]) -> list[dict[str, str]]:
    return [
        {
            "id": value,
            "name_ru": names.get(value) or catalog_names.get(value) or value,
        }
        for value in values
    ]


def _evaluate_recipe(
    recipe: dict[str, Any],
    *,
    type_counts: Counter[str],
    tag_counts: Counter[str],
    names: dict[str, str],
    catalog_names: dict[str, str],
) -> dict[str, Any]:
    inputs: list[dict[str, Any]] = []
    missing = 0
    unverified = 0
    for requirement in recipe.get("inputs") or []:
        row = dict(requirement)
        alternatives = list(row.get("alternatives") or [])
        if row.get("kind") == "item" and row.get("matchKind") == "fullTypes":
            available = sum(float(type_counts[value]) for value in alternatives)
        elif row.get("kind") == "item" and row.get("matchKind") == "tags":
            available = sum(float(tag_counts[value]) for value in alternatives)
        else:
            available = None
            unverified += 1
        required = float(row.get("amount") or 0)
        enough = available is not None and available >= required
        if available is not None and not enough:
            missing += 1
        row["available"] = available
        row["enough"] = enough if available is not None else None
        row["alternatives_ru"] = _localized_alternatives(alternatives, names, catalog_names)
        inputs.append(row)
    outputs = []
    for output in recipe.get("outputs") or []:
        row = dict(output)
        row["alternatives_ru"] = _localized_alternatives(
            list(row.get("alternatives") or []), names, catalog_names
        )
        outputs.append(row)
    exact = missing == 0 and unverified == 0 and bool(inputs)
    return {
        "recipeId": recipe.get("recipeId"),
        "name_ru": recipe.get("name_ru"),
        "category": recipe.get("category"),
        "craftableNowExact": exact,
        "missingInputGroups": missing,
        "unverifiedInputGroups": unverified,
        "needToBeLearned": recipe.get("needToBeLearned"),
        "inputs": inputs,
        "outputs": outputs,
        "source": recipe.get("source"),
    }


def build_supply_calculations(
    snapshot: dict[str, Any],
    *,
    game_path: Path,
    request: dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    all_instances = list(flatten_state(snapshot).values())
    owned = [item for item in all_instances if bool((item.get("source") or {}).get("owned"))]
    type_counts, tag_counts, names = _availability(owned)
    catalog = load_recipe_catalog(game_path)
    catalog_names = catalog.pop("itemNames")
    catalog.pop("evolvedNames", None)

    scope_counts = Counter(str((item.get("source") or {}).get("scope") or "unknown") for item in owned)
    category_counts = Counter(str(item.get("displayCategory") or item.get("category") or "Прочее") for item in owned)
    weight_total = round(sum(float(item.get("actualWeight") or item.get("weight") or 0) for item in owned), 3)
    duplicate_groups = [
        {
            "fullType": full_type,
            "name_ru": names.get(full_type) or catalog_names.get(full_type) or full_type,
            "quantity": int(count) if float(count).is_integer() else round(float(count), 3),
        }
        for full_type, count in type_counts.items()
        if count > 1
    ]
    duplicate_groups.sort(key=lambda row: (-float(row["quantity"]), str(row["name_ru"])))

    edible = []
    disposal = []
    for item in owned:
        if item.get("itemType") != "food":
            continue
        food = item.get("food") or {}
        row = {
            "fullType": item.get("fullType"),
            "name_ru": item.get("name_ru") or item.get("nameLocalized"),
            "calories": round(float(food.get("calories") or 0), 2),
            "freshness": food.get("freshnessStage"),
            "frozen": bool(food.get("frozen")),
            "cooked": bool(food.get("cooked")),
            "rotten": bool(food.get("rotten")),
            "evolvedRecipeName": food.get("evolvedRecipeName"),
            "location_ru": (item.get("source") or {}).get("containerDisplayName") or "Инвентарь персонажа",
        }
        if _is_disposal(item) or row["rotten"]:
            disposal.append(row)
        else:
            edible.append(row)
    edible.sort(key=lambda row: (-float(row["calories"]), str(row["name_ru"])))

    evaluated = [
        _evaluate_recipe(
            recipe,
            type_counts=type_counts,
            tag_counts=tag_counts,
            names=names,
            catalog_names=catalog_names,
        )
        for recipe in catalog.get("recipes") or []
    ]
    craftable = [recipe for recipe in evaluated if recipe["craftableNowExact"]]
    near = [
        recipe for recipe in evaluated
        if not recipe["craftableNowExact"]
        and recipe["missingInputGroups"] <= 2
        and recipe["unverifiedInputGroups"] == 0
    ]

    ingredient_recipes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in edible:
        evolved_value = item.get("evolvedRecipeName")
        if not isinstance(evolved_value, str):
            continue
        for option in evolved_value.split(";"):
            definition = option.strip().partition("|")[0]
            recipe_name = definition.rpartition(":")[0] or definition
            recipe_name = recipe_name.strip()
            if recipe_name:
                ingredient_recipes[recipe_name].append(item)

    evolved_options = []
    for name, candidates in ingredient_recipes.items():
        definition = (catalog.get("evolvedRecipes") or {}).get(name) or {
            "recipeId": name,
            "internalName": name,
            "name_ru": name,
        }
        base_item = definition.get("baseItem")
        evolved_options.append(
            {
                **definition,
                "baseItemAvailable": bool(base_item and type_counts[str(base_item)] > 0),
                "ingredientKindsAvailable": len({str(item.get("fullType")) for item in candidates}),
                "ingredientInstancesAvailable": len(candidates),
                "knownIngredientCaloriesAvailable": round(sum(float(item.get("calories") or 0) for item in candidates), 2),
                "highestCalorieIngredients": candidates[:12],
                "calorieRule_ru": (
                    "Это сумма известных калорий доступных ингредиентов для ранжирования, "
                    "а не гарантированная калорийность одной готовой порции."
                ),
            }
        )
    evolved_options.sort(
        key=lambda row: (-float(row.get("knownIngredientCaloriesAvailable") or 0), str(row.get("name_ru") or row.get("internalName")))
    )

    raw_sequence = int((snapshot.get("runtimeExport") or {}).get("sequence") or 0)
    return {
        "schema": "pz-monitoring-bot/supply-calculations/v1",
        "createdAt": created_at,
        "requestId": request.get("requestId"),
        "saveId": (snapshot.get("save") or {}).get("id"),
        "snapshotSequence": raw_sequence,
        "requestedSnapshotSequence": request.get("snapshotSequence"),
        "currentForRequestedSnapshot": int(request.get("snapshotSequence") or -1) == raw_sequence,
        "game": {
            "reportedBuild": (snapshot.get("game") or {}).get("build"),
            "catalogSource": str(game_path),
            "catalogCompatibility": "Build 42.20.x installed files",
        },
        "inventory": {
            "itemInstances": len(owned),
            "distinctFullTypes": len(type_counts),
            "totalActualWeight": weight_total,
            "byScope": dict(sorted(scope_counts.items())),
            "byCategory": dict(sorted(category_counts.items())),
            "duplicateGroups": duplicate_groups,
        },
        "food": {
            "edibleItemInstances": len(edible),
            "knownCaloriesTotal": round(sum(float(item["calories"]) for item in edible), 2),
            "highCalorieItems": edible[:30],
            "compostOrDisposalItems": disposal,
        },
        "recipes": {
            "source": catalog.get("source"),
            "recipeFilesParsed": catalog.get("recipeFilesParsed"),
            "cookingRecipesParsed": len(evaluated),
            "craftableNowExactCount": len(craftable),
            "craftableNowExact": craftable,
            "nearlyCraftable": near,
            "allCookingRecipes": evaluated,
            "evolvedDishOptions": evolved_options,
            "rule_ru": (
                "craftableNowExact учитывает только явно описанные предметы и теги. "
                "Рецепты с жидкостями, mapper или неизвестными условиями не объявляются готовыми без проверки."
            ),
        },
    }
