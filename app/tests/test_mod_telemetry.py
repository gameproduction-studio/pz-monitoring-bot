from __future__ import annotations

import copy
from pathlib import Path

from pzbot.assistant_views import build_assistant_views
from pzbot.cli import _parser
from pzbot.mod_telemetry import normalize_mod_snapshot
from pzbot.state_diff import compare_states, flatten_state


def runtime_item(item_id: int, full_type: str, name: str, **fields):
    return {
        "itemId": str(item_id),
        "fullType": full_type,
        "nameLocalized": name,
        "quantity": 1,
        "condition": 10,
        "conditionMax": 10,
        "currentUses": 1,
        "uses": 1,
        "tags": [],
        **fields,
    }


def runtime_state(*, character=None, containers=None, sequence=1):
    return {
        "schema": "pz-monitoring-bot/mod-snapshot/v1",
        "source": {"kind": "in_game_mod", "readOnly": True},
        "game": {"build": "42.20.3", "worldAgeHours": 100.0},
        "save": {"id": "Sandbox:test", "name": "test", "gameMode": "Sandbox"},
        "export": {"sequence": sequence, "writtenAtEpochMs": 1_700_000_000_000},
        "character": {
            "name": "Nathan Reed",
            "position": {"x": 0, "y": 0, "z": 0},
            "inventory": {"items": character or []},
        },
        "world": {
            "containers": containers or [],
            "coverage": {"runtimeLoadedOnly": True},
        },
        "baseZones": [],
    }


def runtime_container(
    container_id: str,
    items,
    *,
    owned=True,
    stale_name="Kitchen shelf",
    position=None,
):
    return {
        "containerId": container_id,
        "kind": "stationary",
        "containerType": "counter",
        "displayName": stale_name,
        "customName": stale_name,
        "position": position or {"x": 10, "y": 11, "z": 0},
        "ownership": {
            "owned": owned,
            "reason": "opened_by_player" if owned else "observed_only",
        },
        "observation": "selected_by_player",
        "lastSeenWorldAgeHours": 100,
        "items": items,
    }


def test_sequential_snapshots_distinguish_income_move_food_change_and_expense():
    peach = runtime_item(
        1,
        "Base.Peach",
        "Fresh peach",
        food={
            "calories": 58,
            "ageDays": 1,
            "daysFresh": 3,
            "daysTotallyRotten": 6,
            "freshnessStage": "fresh",
            "frozen": True,
            "freezingTime": 100,
            "cookable": False,
        },
    )
    first = normalize_mod_snapshot(runtime_state(character=[]))
    second = normalize_mod_snapshot(runtime_state(character=[peach], sequence=2), previous=first)
    assert [event["kind"] for event in compare_states(first, second)] == ["incoming"]

    third_raw = runtime_state(
        containers=[runtime_container("world:10:11:0:1:0:counter", [peach])],
        sequence=3,
    )
    third = normalize_mod_snapshot(third_raw, previous=second)
    assert [event["kind"] for event in compare_states(second, third)] == ["move"]

    thawed = copy.deepcopy(peach)
    thawed["food"].update(frozen=False, freezingTime=0, ageDays=1.2)
    fourth = normalize_mod_snapshot(
        runtime_state(
            containers=[runtime_container("world:10:11:0:1:0:counter", [thawed])],
            sequence=4,
        ),
        previous=third,
    )
    assert "food_thawed" in [event["kind"] for event in compare_states(third, fourth)]

    fifth = normalize_mod_snapshot(
        runtime_state(
            containers=[runtime_container("world:10:11:0:1:0:counter", [])],
            sequence=5,
        ),
        previous=fourth,
    )
    assert [event["kind"] for event in compare_states(fourth, fifth)] == ["outgoing"]


def test_nested_portable_container_and_human_location_are_preserved():
    paper = runtime_item(11, "Base.SheetPaper2", "Paper sheet")
    case = runtime_item(
        10,
        "Base.GunCase",
        "Weapon case",
        container={
            "type": "container",
            "capacity": 15,
            "weightReduction": 10,
            "items": [paper],
        },
    )
    snapshot = normalize_mod_snapshot(runtime_state(character=[case]))
    flat = flatten_state(snapshot)
    assert flat["11"]["parentItemIds"] == ["10"]
    assert flat["11"]["source"]["containerDisplayName"] == "Weapon case"
    views = build_assistant_views(snapshot)
    assert views["ownedItemsByLocation"]["Weapon case"][0]["fullType"] == "Base.SheetPaper2"


def test_stale_container_is_carried_forward_but_does_not_duplicate_moved_item():
    hammer = runtime_item(21, "Base.Hammer", "Hammer")
    old = normalize_mod_snapshot(
        runtime_state(containers=[runtime_container("world:old", [hammer])])
    )
    new = normalize_mod_snapshot(runtime_state(character=[hammer], sequence=2), previous=old)
    stale = next(container for container in new["world"]["containers"] if container["containerId"] == "world:old")
    assert stale["observation"]["stale"] is True
    assert stale["items"] == []
    assert list(flatten_state(new)) == ["21"]


def test_food_view_reports_game_calories_and_no_power_warning():
    sausage = runtime_item(
        31,
        "Base.Sausage",
        "Fresh sausage",
        food={
            "calories": 300,
            "ageDays": 1,
            "daysFresh": 2,
            "daysTotallyRotten": 4,
            "freshnessStage": "fresh",
            "frozen": False,
            "freezingTime": 0,
            "cookable": True,
            "dangerousUncooked": True,
            "evolvedRecipeName": "Stew:12;Sandwich:6|Cooked",
        },
    )
    snapshot = normalize_mod_snapshot(runtime_state(character=[sausage]))
    food = build_assistant_views(snapshot)["food"]
    assert food["totalCaloriesReportedByGame"] == 300
    assert food["highCalorieOwned"][0]["fullType"] == "Base.Sausage"
    assert food["cookingCandidates"][0]["cookable"] is True
    assert food["owned"][0]["recipeOptions"] == [
        {"recipeId": "Stew", "ingredientAmount": 12.0, "requiresCookedIngredient": False},
        {"recipeId": "Sandwich", "ingredientAmount": 6.0, "requiresCookedIngredient": True},
    ]
    assert {alert["kind"] for alert in food["spoilageAlerts"]} == {
        "perishable_in_unsuitable_storage"
    }


def test_cli_exposes_mod_relay_without_starting_a_watcher():
    parser = _parser()
    assert parser.parse_args(["relay"]).command == "relay"
    assert parser.parse_args(["relay-monitor"]).command == "relay-monitor"


def test_lua_scanner_was_not_truncated():
    root = Path(__file__).parents[2]
    scanner = root / "mod/PZMonitoringBot/common/media/lua/client/PZMonitoringBot/PZMB_Scanner.lua"
    text = scanner.read_text(encoding="utf-8")
    assert text.rstrip().endswith("return Scanner")
    assert "function Scanner.currentState()" in text
