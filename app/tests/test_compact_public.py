from __future__ import annotations

import json

from pzbot.live_contract import build_current_state, write_live_files


def test_public_state_omits_duplicate_flat_item_list_and_writes_compact_json(tmp_path):
    item = {
        "fullType": "Base.Hammer",
        "itemIds": ["1"],
        "quantity": 1,
        "name_ru": "Молоток",
        "condition": 10,
        "conditionMax": 10,
    }
    snapshot = {
        "save": {"id": "Sandbox:test", "name": "test", "gameMode": "Sandbox"},
        "game": {"build": "42.20.3", "worldAgeHours": 10},
        "character": {
            "position": {"x": 0, "y": 0, "z": 0},
            "inventory": {"items": [item]},
        },
        "world": {"containers": [], "vehicles": [], "corpses": [], "groundItems": []},
        "baseZones": [],
    }
    state = build_current_state(
        snapshot,
        events=[{"type": "item_added", "item": {"payload": "large duplicate"}}],
        scan_time="2026-01-01T00:00:00+00:00",
    )
    assert "items" not in state
    assert state["itemList"]["omittedFromPublicSnapshot"] is True
    assert state["itemList"]["count"] == 1
    assert state["recentChanges"] == {
        "omittedFromCurrentState": True,
        "source": "changes.jsonl",
        "count": 1,
    }

    write_live_files(
        tmp_path,
        current_state=state,
        status={"ok": True},
        events=[],
    )
    raw = (tmp_path / "current_state.json").read_text(encoding="utf-8")
    assert '\n  "' not in raw
    assert json.loads(raw)["summary"]["physicalItemsVisible"] == 1
