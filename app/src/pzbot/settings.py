"""Configuration for the local pz monitoring bot."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _expand(value: str, base: Path) -> Path:
    expanded = Path(os.path.expandvars(os.path.expanduser(value)))
    return expanded.resolve() if expanded.is_absolute() else (base / expanded).resolve()


@dataclass(frozen=True)
class PublishSettings:
    enabled: bool
    repository_path: Path
    remote: str
    branch: str
    minimum_interval_seconds: float


@dataclass(frozen=True)
class Settings:
    config_path: Path
    save_root: Path
    game_path: Path
    telemetry_dir: Path
    runtime_dir: Path
    live_dir: Path
    save_override: Path | None
    poll_seconds: float
    stable_polls: int
    stable_interval_seconds: float
    base_zones: tuple[dict[str, Any], ...]
    explicitly_opened_container_ids: frozenset[str]
    manual_owned_container_ids: frozenset[str]
    publish: PublishSettings

    @property
    def state_path(self) -> Path:
        return self.runtime_dir / "pz_inventory_state.json"

    @property
    def log_path(self) -> Path:
        return self.runtime_dir / "pz_monitoring_bot.log"


def load_settings(path: str | Path) -> Settings:
    config_path = Path(path).resolve()
    raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
    base = config_path.parent
    publication = raw.get("publish") or {}
    override = raw.get("save_override")
    return Settings(
        config_path=config_path,
        save_root=_expand(raw.get("save_root", "%USERPROFILE%/Zomboid/Saves"), base),
        game_path=_expand(raw["game_path"], base),
        telemetry_dir=_expand(
            raw.get("telemetry_dir", "%USERPROFILE%/Zomboid/Lua"),
            base,
        ),
        runtime_dir=_expand(raw.get("runtime_dir", "runtime"), base),
        live_dir=_expand(raw.get("live_dir", "../live"), base),
        save_override=_expand(override, base) if override else None,
        poll_seconds=float(raw.get("poll_seconds", 5)),
        stable_polls=int(raw.get("stable_polls", 3)),
        stable_interval_seconds=float(raw.get("stable_interval_seconds", 2)),
        base_zones=tuple(raw.get("base_zones") or ()),
        explicitly_opened_container_ids=frozenset(
            str(value) for value in raw.get("explicitly_opened_container_ids") or ()
        ),
        manual_owned_container_ids=frozenset(
            str(value) for value in raw.get("manual_owned_container_ids") or ()
        ),
        publish=PublishSettings(
            enabled=bool(publication.get("enabled", False)),
            repository_path=_expand(publication.get("repository_path", ".."), base),
            remote=str(publication.get("remote", "origin")),
            branch=str(publication.get("branch", "main")),
            minimum_interval_seconds=float(
                publication.get("minimum_interval_seconds", 20)
            ),
        ),
    )

