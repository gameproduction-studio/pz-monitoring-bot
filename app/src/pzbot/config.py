from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PublishConfig:
    enabled: bool
    repository_path: Path
    branch: str = "main"
    remote: str = "origin"
    minimum_interval_seconds: float = 20.0


@dataclass(frozen=True)
class AppConfig:
    config_path: Path
    save_root: Path
    game_path: Path
    runtime_dir: Path
    poll_seconds: float
    stable_polls: int
    stable_interval_seconds: float
    publish: PublishConfig

    @property
    def database_path(self) -> Path:
        return self.runtime_dir / "pzbot.sqlite3"

    @property
    def log_path(self) -> Path:
        return self.runtime_dir / "pzbot.log"

    @property
    def current_snapshot_path(self) -> Path:
        return self.runtime_dir / "current_snapshot.json"


def _expand(value: str, base: Path) -> Path:
    expanded = Path(os.path.expandvars(os.path.expanduser(value)))
    return expanded if expanded.is_absolute() else (base / expanded).resolve()


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).resolve()
    raw: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8-sig"))
    base = config_path.parent
    publication = raw.get("publish") or {}
    return AppConfig(
        config_path=config_path,
        save_root=_expand(raw["save_root"], base),
        game_path=_expand(raw["game_path"], base),
        runtime_dir=_expand(raw.get("runtime_dir", "runtime"), base),
        poll_seconds=float(raw.get("poll_seconds", 5)),
        stable_polls=int(raw.get("stable_polls", 3)),
        stable_interval_seconds=float(raw.get("stable_interval_seconds", 2)),
        publish=PublishConfig(
            enabled=bool(publication.get("enabled", False)),
            repository_path=_expand(publication.get("repository_path", "."), base),
            branch=str(publication.get("branch", "main")),
            remote=str(publication.get("remote", "origin")),
            minimum_interval_seconds=float(publication.get("minimum_interval_seconds", 20)),
        ),
    )

