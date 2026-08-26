from __future__ import annotations

import json
from pathlib import Path
from urllib.request import urlopen

import pytest

from pzbot.dashboard import build_dashboard_payload, start_dashboard
from pzbot.settings import DashboardSettings, PublishSettings, Settings


def settings_for(tmp_path: Path, *, host: str = "127.0.0.1") -> Settings:
    return Settings(
        config_path=tmp_path / "config.json",
        save_root=tmp_path / "saves",
        game_path=tmp_path / "game",
        telemetry_dir=tmp_path / "telemetry",
        runtime_dir=tmp_path / "runtime",
        live_dir=tmp_path / "live",
        save_override=None,
        poll_seconds=1,
        stable_polls=1,
        stable_interval_seconds=0,
        base_zones=(),
        explicitly_opened_container_ids=frozenset(),
        manual_owned_container_ids=frozenset(),
        publish=PublishSettings(False, tmp_path, "origin", "main", 20),
        dashboard=DashboardSettings(True, host, 0, "auto"),
    )


def write_contract(settings: Settings) -> None:
    chatgpt = settings.live_dir / "chatgpt"
    chatgpt.mkdir(parents=True)
    overview = {
        "snapshot": {"saveId": "Sandbox:test", "sequence": 7},
        "character": {"name": "Nathan Reed"},
    }
    (chatgpt / "overview.json").write_text(
        json.dumps(overview), encoding="utf-8"
    )
    bootstrap = {
        "status": {
            "ok": True,
            "parsingSuccessful": True,
            "lastScanAt": "2026-08-26T00:00:00+00:00",
            "activeSave": {"id": "Sandbox:test", "name": "test"},
            "modStatus": {
                "sequence": 7,
                "game": {"language": "RU"},
            },
        },
        "sectionPaths": {"overview": "live/chatgpt/overview.json"},
    }
    (settings.live_dir / "chatgpt_state.json").write_text(
        json.dumps(bootstrap), encoding="utf-8"
    )


def test_dashboard_payload_follows_contract_paths_and_game_language(tmp_path: Path):
    settings = settings_for(tmp_path)
    write_contract(settings)
    payload = build_dashboard_payload(settings)
    assert payload["language"]["selected"] == "RU"
    assert payload["sections"]["overview"]["character"]["name"] == "Nathan Reed"
    assert payload["sections"]["food"] is None


def test_dashboard_serves_assets_health_and_data_on_loopback(tmp_path: Path):
    settings = settings_for(tmp_path)
    write_contract(settings)
    handle = start_dashboard(settings)
    try:
        with urlopen(handle.url + "api/v1/health", timeout=3) as response:
            health = json.load(response)
            assert health["sequence"] == 7
            assert response.headers["X-Frame-Options"] == "DENY"
        with urlopen(handle.url, timeout=3) as response:
            assert b"PZ Organizer" in response.read()
        with urlopen(handle.url + "api/v1/dashboard", timeout=3) as response:
            assert json.load(response)["language"]["selected"] == "RU"
    finally:
        handle.stop()


def test_dashboard_rejects_non_loopback_bind(tmp_path: Path):
    settings = settings_for(tmp_path, host="0.0.0.0")
    with pytest.raises(ValueError, match="loopback"):
        start_dashboard(settings)
