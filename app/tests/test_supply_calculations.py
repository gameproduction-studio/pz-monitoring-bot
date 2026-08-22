from __future__ import annotations

import json

from pzbot.mod_telemetry import normalize_mod_snapshot
from pzbot.public_surface import MAX_CHATGPT_FILE_BYTES, build_public_files
from pzbot.supply_calculations import build_supply_calculations

from test_mod_telemetry import runtime_item, runtime_state


def _game_catalog(tmp_path):
    game = tmp_path / "game"
    recipes = game / "media/scripts/generated/recipes"
    recipes.mkdir(parents=True)
    items = game / "media/scripts/generated/items"
    items.mkdir(parents=True)
    (items / "food.txt").write_text(
        """
module Base
{
    item Carrots
    {
        ItemType = base:food,
        EvolvedRecipe = Stew:12;Soup:12,
        HungerChange = -10,
        Calories = 25,
        Carbohydrates = 6,
        Proteins = 1,
    }
}
""",
        encoding="utf-8",
    )
    (recipes / "recipes_cooking.txt").write_text(
        """
module Base
{
    craftRecipe MakeTestStew
    {
        category = Cooking,
        inputs
        {
            item 1 [Base.Pot] mode:keep,
            item 1 tags[base:vegetable],
        }
        outputs
        {
            item 1 Base.PotOfStew,
        }
    }
}
""",
        encoding="utf-8",
    )
    (game / "media/scripts/generated/evolvedrecipes.txt").write_text(
        """
module Base
{
    evolvedrecipe Stew
    {
        BaseItem = Base.Pot,
        MaxItems = 6,
        ResultItem = Base.PotOfStew,
        Cookable = true,
        Name = Prepare Stew,
        Template = Stew,
        MinimumWater = 0.9,
    }
}
""",
        encoding="utf-8",
    )
    locale = game / "media/lua/shared/Translate/RU"
    locale.mkdir(parents=True)
    (locale / "Recipes.json").write_text(
        json.dumps(
            {
                "MakeTestStew": "Приготовить тестовое рагу",
                "Prepare Stew": "Приготовить рагу",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (locale / "ItemName.json").write_text(
        json.dumps({"Base.PotOfStew": "Кастрюля рагу"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (locale / "EvolvedRecipeName.json").write_text("{}", encoding="utf-8")
    return game


def test_offline_calculations_match_owned_items_and_installed_recipes(tmp_path):
    game = _game_catalog(tmp_path)
    pot = runtime_item(1, "Base.Pot", "Кастрюля")
    carrot = runtime_item(
        2,
        "Base.Carrots",
        "Морковь",
        tags=["base:vegetable"],
        food={
            "calories": 25,
            "freshnessStage": "fresh",
            "evolvedRecipeName": "Stew:12;Soup:12",
        },
    )
    snapshot = normalize_mod_snapshot(runtime_state(character=[pot, carrot], sequence=7))
    calculations = build_supply_calculations(
        snapshot,
        game_path=game,
        request={"requestId": "7:test", "snapshotSequence": 7},
        created_at="now",
    )

    assert calculations["currentForRequestedSnapshot"] is True
    assert calculations["inventory"]["itemInstances"] == 2
    assert calculations["food"]["knownCaloriesTotal"] == 25
    assert calculations["recipes"]["craftableNowExactCount"] == 1
    recipe = calculations["recipes"]["craftableNowExact"][0]
    assert recipe["name_ru"] == "Приготовить тестовое рагу"
    assert recipe["craftableNowExact"] is True
    evolved = next(
        row for row in calculations["recipes"]["evolvedDishOptions"]
        if row.get("internalName") == "Stew"
    )
    assert evolved["name_ru"] == "Приготовить рагу"
    assert evolved["baseItemAvailable"] is True


def test_calculation_surface_is_paged_and_connector_safe(tmp_path):
    game = _game_catalog(tmp_path)
    snapshot = normalize_mod_snapshot(
        runtime_state(
            character=[
                runtime_item(1, "Base.Pot", "Кастрюля"),
                runtime_item(
                    2,
                    "Base.Carrots",
                    "Морковь",
                    tags=["base:vegetable"],
                    food={"calories": 25, "freshnessStage": "fresh"},
                ),
            ],
            sequence=7,
        )
    )
    calculations = build_supply_calculations(
        snapshot,
        game_path=game,
        request={"requestId": "7:test", "snapshotSequence": 7},
        created_at="now",
    )
    current = {
        "character": snapshot["character"],
        "supplyCalculations": calculations,
    }
    public = {
        "updatedAt": "now",
        "save": snapshot["save"],
        "status": {
            "lastScanAt": "now",
            "lastGameExportEpochMs": 1,
            "calculations": {"ready": True, "currentForSnapshot": True},
        },
        "assistantViews": {"food": {}, "resources": {}, "vehicles": {"owned": []}},
    }
    files, manifest, bootstrap = build_public_files(current, public)
    calculations_index = files["calculations.json"]

    assert bootstrap["sectionPaths"]["calculations"] == "live/chatgpt/calculations.json"
    assert calculations_index["status"]["ready"] is True
    assert calculations_index["craftableRecipePages"]
    assert calculations_index["mealPlanPages"]
    meal_records = [
        record
        for path in calculations_index["mealPlanPages"]
        for record in files[path.removeprefix("live/chatgpt/")]["records"]
    ]
    assert any(record["profile"] == "balanced_nutrition" for record in meal_records)
    assert all(entry["withinConnectorLimit"] for entry in manifest["files"])
    assert all(
        len((json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
        <= MAX_CHATGPT_FILE_BYTES
        for payload in files.values()
    )
