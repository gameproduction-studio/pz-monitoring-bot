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
    assert (tmp_path / "chatgpt_state.json").is_file()


def test_public_journal_reports_truncation_and_survives_relay_restart(tmp_path):
    snapshot = {
        "save": {"id": "Sandbox:test", "name": "test", "gameMode": "Sandbox"},
        "game": {"build": "42.20.3", "worldAgeHours": 10},
        "character": {"position": {"x": 0, "y": 0, "z": 0}, "inventory": {"items": []}},
        "world": {"containers": [], "vehicles": [], "corpses": [], "groundItems": []},
        "baseZones": [],
    }
    current = build_current_state(snapshot, events=[], scan_time="2026-01-01T00:00:00+00:00")
    status = {
        "ok": True,
        "activeSave": {"id": "Sandbox:test"},
        "modStatus": {"sequence": 9},
        "changesThisScan": 150,
    }
    events = [{"kind": "move", "itemId": str(index)} for index in range(150)]
    write_live_files(tmp_path, current_state=current, status=status, events=events)
    first = json.loads((tmp_path / "chatgpt_state.json").read_text(encoding="utf-8"))
    assert first["recentChangesMeta"] == {
        "totalDetected": 150,
        "returned": 100,
        "limit": 100,
        "truncated": True,
    }
    assert first["recentChanges"][0]["itemId"] == "50"

    write_live_files(tmp_path, current_state=current, status=status, events=[])
    restarted = json.loads((tmp_path / "chatgpt_state.json").read_text(encoding="utf-8"))
    assert restarted["recentChanges"] == first["recentChanges"]
    assert restarted["recentChangesMeta"] == first["recentChangesMeta"]
    assert restarted["status"]["changesThisScan"] == 150

    previous_public_bytes = (tmp_path / "chatgpt_state.json").read_bytes()
    later_current = build_current_state(
        snapshot,
        events=[],
        scan_time="2026-01-01T00:10:00+00:00",
    )
    write_live_files(tmp_path, current_state=later_current, status=status, events=[])
    assert (tmp_path / "chatgpt_state.json").read_bytes() == previous_public_bytes

    next_status = {**status, "modStatus": {"sequence": 10}, "changesThisScan": 0}
    write_live_files(tmp_path, current_state=current, status=next_status, events=[])
    next_export = json.loads((tmp_path / "chatgpt_state.json").read_text(encoding="utf-8"))
    assert next_export["recentChanges"] == []
    assert next_export["recentChangesMeta"]["totalDetected"] == 0