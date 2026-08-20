from __future__ import annotations

from pzbot.assistant_views import build_assistant_views
from pzbot.mod_telemetry import normalize_mod_snapshot

from test_mod_telemetry import runtime_container, runtime_item, runtime_state


def backpack(item_id: int, capacity: int):
    return runtime_item(
        item_id,
        "Base.Bag_BigHikingBag",
        "Large hiking bag",
        container={
            "type": "bag",
            "capacity": capacity,
            "weightReduction": 80,
            "items": [],
        },
    )


def test_search_can_choose_largest_then_nearest_known_backpack():
    small_near = runtime_container(
        "world:small",
        [backpack(601, 22)],
        owned=False,
        stale_name="Hall shelf",
        position={"x": 2, "y": 0, "z": 0},
    )
    large_far = runtime_container(
        "world:large-far",
        [backpack(602, 28)],
        owned=False,
        stale_name="Wardrobe in northern house",
        position={"x": 12, "y": 0, "z": 0},
    )
    large_near = runtime_container(
        "world:large-near",
        [backpack(603, 28)],
        owned=False,
        stale_name="Corpse by the road",
        position={"x": 3, "y": 4, "z": 0},
    )
    snapshot = normalize_mod_snapshot(
        runtime_state(containers=[small_near, large_far, large_near])
    )
    search = build_assistant_views(snapshot)["search"]
    hiking_bags = [
        item
        for item in search["items"]
        if item["fullType"] == "Base.Bag_BigHikingBag"
    ]
    largest_capacity = max(item["capacity"] for item in hiking_bags)
    best = min(
        (item for item in hiking_bags if item["capacity"] == largest_capacity),
        key=lambda item: item["distanceTiles"],
    )
    assert best["itemId"] == "603"
    assert best["distanceTiles"] == 5
    assert best["directionFromPlayer"] == "SE"
    assert best["location"]["label"] == "Corpse by the road"
    assert best["availability"] == "observed_world"
    assert "unexplored" in search["coverageWarning"]
