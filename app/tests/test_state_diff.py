from __future__ import annotations

import copy

from pzbot.state_diff import compare_states, flatten_state


def grouped(full_type: str, item_id: int, **fields):
    return {
        "fullType": full_type,
        "itemIds": [item_id],
        "quantity": 1,
        "condition": 10,
        "conditionMax": 10,
        **fields,
    }


def snapshot(*, character=None, containers=None, ground=None):
    return {
        "save": {"id": "save-a", "name": "Test", "gameMode": "Sandbox"},
        "worldVersion": 249,
        "character": {"inventory": {"items": character or []}},
        "world": {
            "containers": containers or [],
            "groundItems": ground or [],
            "vehicles": [],
            "corpses": [],
        },
    }


def container(container_id: str, items, *, owned=False):
    return {
        "containerId": container_id,
        "kind": "stationary",
        "containerType": "crate",
        "position": {"x": 10, "y": 10, "z": 0},
        "ownership": {
            "owned": owned,
            "confidence": "exact" if owned else "none",
        },
        "items": items,
    }


def kinds(events):
    return [event["kind"] for event in events]


def test_incoming_and_outgoing_are_physical_item_events():
    old = snapshot(character=[grouped("Base.A", 1)])
    new = snapshot(character=[grouped("Base.B", 2)])
    events = compare_states(old, new, timestamp="2026-01-01T00:00:00+00:00")
    assert kinds(events) == ["incoming", "outgoing"]
    assert {event["itemId"] for event in events} == {"1", "2"}


def test_same_item_id_moved_is_not_income_or_expense():
    item = grouped("Base.Hammer", 10)
    old = snapshot(character=[item])
    new = snapshot(containers=[container("world:1", [copy.deepcopy(item)], owned=True)])
    events = compare_states(old, new)
    assert kinds(events) == ["move"]
    assert events[0]["quantityDelta"] == 0
    assert events[0]["from"].startswith("character/")
    assert events[0]["to"].startswith("world/container:")


def test_condition_food_thaw_rot_and_partial_use():
    old = snapshot(
        character=[
            grouped(
                "Base.Food",
                20,
                itemType="food",
                condition=8,
                age=1.0,
                freshness="fresh",
                frozen=True,
                remainingFraction=1.0,
                currentUses=2,
            )
        ]
    )
    thawed = copy.deepcopy(old)
    food = thawed["character"]["inventory"]["items"][0]
    food.update(condition=6, age=2.0, frozen=False, remainingFraction=0.5, currentUses=1)
    events = compare_states(old, thawed)
    assert "condition_change" in kinds(events)
    assert "food_thawed" in kinds(events)

    rotten = copy.deepcopy(thawed)
    rotten_food = rotten["character"]["inventory"]["items"][0]
    rotten_food.update(age=20.0, freshness="rotten")
    events = compare_states(thawed, rotten)
    assert "food_rotted" in kinds(events)


def test_ammo_loaded_is_classified_from_instance_ids():
    weapon = grouped("Base.Shotgun", 30, itemType="weapon", currentAmmoCount=0)
    shell1 = grouped("Base.ShotgunShells", 31)
    shell2 = grouped("Base.ShotgunShells", 32)
    old = snapshot(character=[weapon, shell1, shell2])
    loaded_weapon = copy.deepcopy(weapon)
    loaded_weapon["currentAmmoCount"] = 2
    new = snapshot(character=[loaded_weapon])
    events = compare_states(old, new)
    ammo = next(event for event in events if event["kind"] == "weapon_ammo_change")
    assert ammo["ammoDelta"] == 2
    assert ammo["classification"] == "loaded"


def test_nested_container_content_is_flattened_with_parent_id():
    case = grouped(
        "Base.Case",
        40,
        itemType="container",
        contents=[grouped("Base.Paper", 41)],
    )
    state = snapshot(character=[case])
    items = flatten_state(state)
    assert items["41"]["parentItemIds"] == ["40"]
    assert items["41"]["source"]["path"].endswith("item:40")

