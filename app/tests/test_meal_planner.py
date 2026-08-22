from __future__ import annotations

import json

from pzbot.mod_telemetry import normalize_mod_snapshot
from pzbot.supply_calculations import build_supply_calculations

from test_mod_telemetry import runtime_item, runtime_state


def _game(tmp_path):
    game = tmp_path / "game"
    (game / "media/scripts/generated/recipes").mkdir(parents=True)
    items = game / "media/scripts/generated/items"
    items.mkdir(parents=True)
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
    (items / "food.txt").write_text(
        """
module Base
{
    item DriedBlackBeans
    {
        ItemType = base:food,
        EvolvedRecipe = Soup:10;Stew:10;Rice:10;Pasta:10,
        EvolvedRecipeName = Black Bean,
        HungerChange = -60.0,
        Calories = 3084.0,
        Carbohydrates = 580.0,
        Lipids = 0.0,
        Proteins = 199.0,
    }
    item DriedLentils
    {
        ItemType = base:food,
        EvolvedRecipe = Soup:10;Stew:10;Rice:10;Pasta:10,
        EvolvedRecipeName = Lentil,
        HungerChange = -60.0,
        Calories = 3000.0,
        Carbohydrates = 540.0,
        Lipids = 0.0,
        Proteins = 220.0,
    }
    item Rabbitmeat
    {
        ItemType = base:food,
        EvolvedRecipe = Soup:15;Stew:15;Rice:15;Pasta:15,
        EvolvedRecipeName = Rabbit,
        HungerChange = -30.0,
        Calories = 969.0,
        Carbohydrates = 20.0,
        Lipids = 20.0,
        Proteins = 185.0,
    }
    item OilVegetable
    {
        ItemType = base:food,
        EvolvedRecipe = Soup:5;Stew:5,
        Spice = true,
        HungerChange = -30.0,
        Calories = 2120.0,
        Carbohydrates = 0.0,
        Lipids = 130.0,
        Proteins = 0.0,
    }
}
""",
        encoding="utf-8",
    )
    locale = game / "media/lua/shared/Translate/RU"
    locale.mkdir(parents=True)
    (locale / "Recipes.json").write_text(
        json.dumps({"Prepare Stew": "Приготовить рагу"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (locale / "ItemName.json").write_text(
        json.dumps(
            {
                "Base.Pot": "Кастрюля",
                "Base.PotOfStew": "Кастрюля рагу",
                "Base.DriedBlackBeans": "Чёрная фасоль (сушёное)",
                "Base.DriedLentils": "Чечевица (сушёное)",
                "Base.Rabbitmeat": "Крольчатина",
                "Base.OilVegetable": "Растительное масло",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (locale / "EvolvedRecipeName.json").write_text("{}", encoding="utf-8")
    return game


def _food(item_id, full_type, name, *, uses, calories, hunger, carbs=0, lipids=0, proteins=0):
    return runtime_item(
        item_id,
        full_type,
        name,
        currentUses=uses,
        food={
            "calories": calories,
            "hungerChange": hunger,
            "carbohydrates": carbs,
            "lipids": lipids,
            "proteins": proteins,
            "freshnessStage": "fresh",
            # Deliberately misleading runtime value: compatibility must come
            # from installed scripts, not getEvolvedRecipeName().
            "evolvedRecipeName": full_type,
        },
    )


def test_build_42_stew_plan_uses_exact_matrix_and_includes_rabbit(tmp_path):
    game = _game(tmp_path)
    items = [
        runtime_item(1, "Base.Pot", "Кастрюля"),
        *[runtime_item(10 + index, "Base.Bowl", "Миска") for index in range(4)],
        _food(20, "Base.DriedBlackBeans", "Чёрная фасоль (сушёное)", uses=60, calories=3084, hunger=-0.6, carbs=580, proteins=199),
        _food(21, "Base.DriedLentils", "Чечевица (сушёное)", uses=60, calories=3000, hunger=-0.6, carbs=540, proteins=220),
        _food(22, "Base.Rabbitmeat", "Крольчатина", uses=10, calories=350, hunger=-0.1, carbs=7, lipids=6, proteins=60),
        _food(23, "Base.OilVegetable", "Растительное масло", uses=30, calories=2120, hunger=-0.3, lipids=130),
    ]
    snapshot = normalize_mod_snapshot(runtime_state(character=items, sequence=9))
    calculations = build_supply_calculations(
        snapshot,
        game_path=game,
        request={"requestId": "9:meal", "snapshotSequence": 9},
        created_at="now",
    )

    recipes = calculations["recipes"]
    assert calculations["schema"] == "pz-monitoring-bot/supply-calculations/v2"
    assert recipes["mealPlanning"]["catalog"]["ingredientDefinitions"] == 4
    stew = next(row for row in recipes["evolvedDishOptions"] if row["internalName"] == "Stew")
    assert stew["baseItemAvailable"] is True
    assert stew["maxItems"] == 6
    assert stew["minimumWater"] == 0.9
    rabbit = next(row for row in stew["compatibleOwnedIngredients"] if row["fullType"] == "Base.Rabbitmeat")
    assert rabbit["useHungerUnitsPerAddition"] == 15

    plan = next(
        row
        for row in recipes["recommendedMealPlans"]
        if row["recipeId"] == "Base.Stew" and row["profile"] == "balanced_nutrition"
    )
    assert plan["mainSlotsUsed"] == 6
    assert any(row["fullType"] == "Base.Rabbitmeat" for row in plan["ingredients"])
    assert any(row["fullType"] == "Base.OilVegetable" for row in plan["recommendedSpices"])
    assert plan["portioning"]["bowls"] == 4
    assert plan["portioning"]["projectedPerBowl"]["calories"] > 500
    assert any("Крольчатина" in step for step in plan["steps_ru"])
