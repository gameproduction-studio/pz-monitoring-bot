from __future__ import annotations

import json
from pathlib import Path

from pzbot.mod_relay import relay_once
from pzbot.settings import PublishSettings, Settings

from test_mod_telemetry import runtime_container, runtime_item, runtime_state


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        config_path=tmp_path / "config.json",
        save_root=tmp_path / "unused-saves",
        game_path=tmp_path / "unused-game",
        telemetry_dir=tmp_path / "telemetry",
        runtime_dir=tmp_path / "runtime",
        live_dir=tmp_path / "live",
        save_override=None,
        poll_seconds=0.01,
        stable_polls=2,
        stable_interval_seconds=0.01,
        base_zones=(),
        explicitly_opened_container_ids=frozenset(),
        manual_owned_container_ids=frozenset(),
        publish=PublishSettings(
            enabled=False,
            repository_path=tmp_path,
            remote="origin",
            branch="main",
            minimum_interval_seconds=0,
        ),
    )


def write_telemetry(settings: Settings, state: dict) -> None:
    settings.telemetry_dir.mkdir(parents=True, exist_ok=True)
    sequence = state["export"]["sequence"]
    status = {
        "schema": "pz-monitoring-bot/mod-status/v1",
        "ok": True,
        "parsingSuccessful": True,
        "sequence": sequence,
        "readOnlyGameState": True,
    }
    (settings.telemetry_dir / "pzmb_current_state.json").write_text(
        json.dumps(state), encoding="utf-8"
    )
    (settings.telemetry_dir / "pzmb_status.json").write_text(
        json.dumps(status), encoding="utf-8"
    )


def test_relay_end_to_end_over_four_snapshots(tmp_path):
    settings = settings_for(tmp_path)
    food = runtime_item(
        501,
        "Base.Sausage",
        "Fresh sausage",
        food={
            "calories": 300,
            "ageDays": 1,
            "daysFresh": 2,
            "daysTotallyRotten": 4,
            "freshnessStage": "fresh",
            "frozen": True,
            "freezingTime": 100,
            "cookable": True,
        },
    )

    write_telemetry(settings, runtime_state(character=[food], sequence=1))
    first = relay_once(settings)
    assert [event["kind"] for event in first["changes"]] == ["incoming"]

    shelf_id = "world:10:11:0:1:0:counter"
    write_telemetry(
        settings,
        runtime_state(
            containers=[runtime_container(shelf_id, [food], stale_name="Food shelf")],
            sequence=2,
        ),
    )
    second = relay_once(settings)
    assert [event["kind"] for event in second["changes"]] == ["move"]

    thawed = json.loads(json.dumps(food))
    thawed["food"].update(frozen=False, freezingTime=0, ageDays=1.25)
    write_telemetry(
        settings,
        runtime_state(
            containers=[runtime_container(shelf_id, [thawed], stale_name="Food shelf")],
            sequence=3,
        ),
    )
    third = relay_once(settings)
    assert "food_thawed" in [event["kind"] for event in third["changes"]]

    write_telemetry(
        settings,
        runtime_state(
            containers=[runtime_container(shelf_id, [], stale_name="Food shelf")],
            sequence=4,
        ),
    )
    fourth = relay_once(settings)
    assert [event["kind"] for event in fourth["changes"]] == ["outgoing"]

    public = json.loads((settings.live_dir / "current_state.json").read_text(encoding="utf-8"))
    status = json.loads((settings.live_dir / "status.json").read_text(encoding="utf-8"))
    history = (settings.live_dir / "changes.jsonl").read_text(encoding="utf-8").splitlines()
    assert public["source"]["gameSaveReadByRelay"] is False
    assert public["assistantViews"]["food"]["owned"] == []
    assert status["ok"] is True
    assert len(history) == 4
    assert (settings.runtime_dir / "pz_inventory_state.json").is_file()
