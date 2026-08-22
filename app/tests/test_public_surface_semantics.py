from __future__ import annotations

import json

from pzbot.public_surface import MAX_CHATGPT_FILE_BYTES, build_public_files


def _state():
    current = {
        "character": {
            "name": "Нэйтан Рид",
            "inventory": {
                "items": [
                    {
                        "fullType": "Base.GunCase",
                        "name_ru": "Оружейный кейс",
                        "itemIds": ["10"],
                        "quantity": 1,
                        "condition": 8,
                        "conditionMax": 10,
                        "contents": [
                            {
                                "fullType": "Base.AlcoholWipes",
                                "name_ru": "Спиртовые салфетки",
                                "itemIds": ["11", "12"],
                                "quantity": 2,
                                "condition": 10,
                                "conditionMax": 10,
                            }
                        ],
                    }
                ]
            },
        }
    }
    public = {
        "updatedAt": "now",
        "save": {"id": "Sandbox:test"},
        "status": {"lastScanAt": "now", "lastGameExportEpochMs": 1},
        "assistantViews": {
            "food": {
                "summary": [
                    {
                        "name_ru": "Хлеб",
                        "fullType": "Base.Bread",
                        "quantity": 2,
                        "freshness": "stale",
                        "rotten": False,
                        "caloriesTotalReportedByGame": 400,
                        "location": {
                            "name_ru": "Мусорка",
                            "containerId": "world:1:bin",
                            "storageType": "bin",
                        },
                    },
                    {
                        "name_ru": "Майонез",
                        "fullType": "Base.MayonnaiseFull",
                        "quantity": 1,
                        "freshness": "fresh",
                        "rotten": False,
                        "frozen": False,
                        "freezingTime": 0.2,
                        "caloriesTotalReportedByGame": 3000,
                        "location": {
                            "name_ru": "Морозильник",
                            "containerId": "world:2:freezer",
                            "storageType": "freezer",
                        },
                    },
                ],
                "highCalorieSummary": [],
                "spoilageAlerts": [
                    {"itemId": "11", "location": "world/container:world:1:bin"},
                    {"itemId": "12", "location": "character/mainInventory"},
                ],
            },
            "resources": {
                "items": [
                    {
                        "name_ru": "Молоток",
                        "fullType": "Base.Hammer",
                        "quantity": 3,
                        "onCharacter": 1,
                        "locations": [
                            {"name_ru": "Инвентарь", "quantity": 1, "scope": "character"},
                            {"name_ru": "Полка", "quantity": 2, "scope": "world"},
                        ],
                    }
                ]
            },
            "vehicles": {"owned": []},
        },
    }
    return current, public


def test_compact_indexes_are_complete_and_human_readable():
    current, public = _state()
    files, manifest, _ = build_public_files(current, public)

    character = files["character.json"]
    wipes = next(row for row in character["inventorySummary"] if row["fullType"] == "Base.AlcoholWipes")
    assert wipes["name_ru"] == "Спиртовые салфетки"
    assert wipes["quantity"] == 2
    assert wipes["locations_ru"] == [
        {"name_ru": "Основной инвентарь / Оружейный кейс", "quantity": 2}
    ]

    resources = files["resources.json"]
    summary_file = resources["summaryPages"][0].rsplit("/", 1)[-1]
    summary_row = files[summary_file]["records"][0]
    assert summary_row["quantity"] == 3
    assert summary_row["inBases"] == 2
    assert resources["duplicateItems"][0]["name_ru"] == "Молоток"

    assert all(entry["withinConnectorLimit"] for entry in manifest["files"])
    assert all(
        len((json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
        <= MAX_CHATGPT_FILE_BYTES
        for payload in files.values()
    )


def test_food_distinguishes_disposal_stale_and_freezing_in_freezer():
    current, public = _state()
    files, _, _ = build_public_files(current, public)

    food_index = files["food.json"]
    food_records = [record for page in food_index["foodPages"] for record in files[page.rsplit("/", 1)[-1]]["records"]]
    bread = next(record for record in food_records if record["fullType"] == "Base.Bread")
    mayonnaise = next(record for record in food_records if record["fullType"] == "Base.MayonnaiseFull")

    assert bread["freshness_ru"] == "Залежавшийся"
    assert bread["edibleStatus"] == "edible_with_penalty"
    assert bread["storageIntent"] == "compost_or_disposal"
    assert bread["excludeFromEdibleStock"] is True
    assert food_index["suppressedDisposalAlerts"] == 1
    assert food_index["spoilageAlerts"] == [
        {"itemId": "12", "location": "character/mainInventory"}
    ]
    assert food_index["compostOrDisposal"]["items"] == 2

    assert mayonnaise["preservationState"] == "freezing_in_freezer"
    assert mayonnaise["protectedByColdStorage"] is True
    assert mayonnaise["attentionRequired"] is False
    assert food_index["edibleStock"] == {
        "groups": 1,
        "items": 1,
        "caloriesReportedByGame": 3000.0,
    }
