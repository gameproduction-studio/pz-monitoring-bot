from __future__ import annotations

import json

from pzbot.live_contract import (
    MAX_PUBLIC_CHANGES_BYTES,
    append_changes,
    build_chatgpt_state,
)


def test_chatgpt_state_removes_large_duplicate_views_but_keeps_facts():
    current = {
        "schemaVersion": "1.1.0",
        "updatedAt": "now",
        "game": {"build": "42.20.3"},
        "save": {"id": "Sandbox:test"},
        "ownership": {"baseZones": []},
        "summary": {"physicalItemsVisible": 1},
        "countsByFullType": {"Base.Hammer": 1},
        "ownedCountsByFullType": {"Base.Hammer": 1},
        "character": {
            "forename": "Нэйтан",
            "position": {"x": 1, "y": 2, "z": 0},
            "inventory": {"items": [{"very": "large"}]},
        },
        "world": {
            "coverage": {"runtimeLoadedOnly": True},
            "containers": [
                {
                    "containerId": "shelf-1",
                    "displayName": "Полка",
                    "kind": "stationary",
                    "position": {"x": 1, "y": 2, "z": 0},
                    "ownership": {"owned": True},
                    "items": [{"fullType": "Base.Hammer"}],
                }
            ],
            "corpses": [],
        },
        "assistantViews": {
            "search": {
                "items": [
                    {
                        "itemId": "1",
                        "fullType": "Base.Hammer",
                        "name_ru": "Молоток",
                        "tags": ["base:tool"],
                        "location": {
                            "label": "Полка",
                            "path": "world/shelf-1",
                            "containerId": "shelf-1",
                            "position": {"x": 1, "y": 2, "z": 0},
                            "owned": True,
                            "stale": False,
                        },
                    }
                ]
            },
            "food": {
                "owned": [],
                "highCalorieOwned": [{"duplicate": True}],
                "cookingCandidates": [{"duplicate": True}],
            },
            "vehicles": {"owned": [{"vehicleId": "7"}]},
            "ownedItemsByLocation": {"Полка": [{"itemId": "1"}]},
        },
        "source": {"primary": "in_game_mod"},
    }

    compact = build_chatgpt_state(
        current,
        status={"ok": True, "activeSave": {"id": "Sandbox:test"}},
        events=[{"kind": "move", "itemId": "1"}],
    )

    assert compact["schema"] == "pz-monitoring-bot/chatgpt-state/v2"
    assert compact["status"]["ok"] is True
    assert compact["recentChanges"] == [{"kind": "move", "itemId": "1"}]
    assert compact["recentChangesMeta"] == {
        "totalDetected": 1,
        "returned": 1,
        "limit": 100,
        "truncated": False,
    }
    assert compact["character"]["forename"] == "Нэйтан"
    assert "inventory" not in compact["character"]
    assert "ownedItemsByLocation" not in compact["assistantViews"]
    assert "highCalorieOwned" not in compact["assistantViews"]["food"]
    assert compact["assistantViews"]["vehicles"]["owned"][0]["vehicleId"] == "7"
    assert compact["worldIndex"]["containers"][0]["itemInstances"] == 1

    search = compact["assistantViews"]["search"]
    item = dict(zip(search["fields"], search["items"][0], strict=True))
    assert item["itemId"] == "1"
    assert item["fullType"] == "Base.Hammer"
    assert item["name_ru"] == "Молоток"
    assert item["condition"] is None
    assert item["locationId"] == "L1"
    assert "tags" not in search["fields"]

    locations = compact["assistantViews"]["locations"]
    location = dict(zip(locations["fields"], locations["items"][0], strict=True))
    assert location["label"] == "Полка"
    assert location["containerId"] == "shelf-1"


def test_public_changes_journal_is_bounded_and_keeps_complete_json_lines(tmp_path):
    path = tmp_path / "changes.jsonl"
    events = [
        {"kind": "move", "itemId": str(index), "payload": "x" * 5000}
        for index in range(250)
    ]

    append_changes(path, events)

    assert path.stat().st_size <= MAX_PUBLIC_CHANGES_BYTES
    parsed = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert parsed
    assert parsed[-1]["itemId"] == "249"
