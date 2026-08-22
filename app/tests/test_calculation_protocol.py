from __future__ import annotations

import json

from pzbot.cli import _telemetry_signature
from pzbot.mod_relay import relay_once

from test_mod_relay_integration import settings_for, write_telemetry
from test_mod_telemetry import runtime_state


def test_calculation_request_is_watched_acknowledged_and_published(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    write_telemetry(settings, runtime_state(sequence=12))
    settings.telemetry_dir.joinpath("pzmb_calculation_request.json").write_text(
        json.dumps(
            {
                "schema": "pz-monitoring-bot/calculation-request/v1",
                "requestId": "12:test",
                "snapshotSequence": 12,
                "kind": "supply_calculations",
            }
        ),
        encoding="utf-8",
    )

    def fake_calculations(snapshot, *, game_path, request, created_at):
        return {
            "schema": "pz-monitoring-bot/supply-calculations/v1",
            "createdAt": created_at,
            "requestId": request["requestId"],
            "saveId": snapshot["save"]["id"],
            "snapshotSequence": snapshot["runtimeExport"]["sequence"],
            "game": {},
            "inventory": {},
            "food": {},
            "recipes": {},
        }

    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    settings.runtime_dir.joinpath("supply_calculations.json").write_text(
        json.dumps(
            {
                "schema": "pz-monitoring-bot/supply-calculations/v1",
                "requestId": "12:test",
                "saveId": "Sandbox:test",
                "snapshotSequence": 12,
                "createdAt": "old-cache",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("pzbot.mod_relay.build_supply_calculations", fake_calculations)
    signature = _telemetry_signature(settings)
    assert any(row[0] == "pzmb_calculation_request.json" for row in signature)

    result = relay_once(settings)
    assert result["calculationsReady"] is True
    response = settings.telemetry_dir.joinpath("pzmb_calculation_response.txt").read_text(
        encoding="utf-8"
    )
    assert response == "12:test\tok\tcompleted_and_published\n"
    status = json.loads(settings.live_dir.joinpath("status.json").read_text(encoding="utf-8"))
    assert status["contractRevision"] == 10
    assert status["calculations"]["ready"] is True
