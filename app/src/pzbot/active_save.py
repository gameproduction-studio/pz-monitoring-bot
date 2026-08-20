"""Resolve the save currently selected by Project Zomboid."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ActiveSave:
    path: Path
    game_mode: str
    folder_name: str
    save_id: str
    selection_source: str

    def public_dict(self) -> dict[str, str]:
        return {
            "id": self.save_id,
            "name": self.folder_name,
            "gameMode": self.game_mode,
            "selectionSource": self.selection_source,
        }


def _identity(game_mode: str, folder_name: str) -> str:
    material = f"{game_mode}/{folder_name}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:20]


def _build(path: Path, save_root: Path, source: str) -> ActiveSave:
    relative = path.resolve().relative_to(save_root.resolve())
    if len(relative.parts) != 2:
        raise ValueError(f"Unexpected save path below {save_root}: {path}")
    game_mode, folder_name = relative.parts
    return ActiveSave(
        path=path.resolve(),
        game_mode=game_mode,
        folder_name=folder_name,
        save_id=_identity(game_mode, folder_name),
        selection_source=source,
    )


def latest_save_ini(save_root: Path) -> Path:
    return save_root.parent / "latestSave.ini"


def from_latest_save_ini(save_root: Path) -> ActiveSave | None:
    ini = latest_save_ini(save_root)
    if not ini.is_file():
        return None
    lines = [
        line.strip()
        for line in ini.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        if line.strip()
    ]
    if len(lines) < 2:
        return None
    folder_name, game_mode = lines[0], lines[1]
    candidate = save_root / game_mode / folder_name
    if not (candidate / "players.db").is_file():
        return None
    return _build(candidate, save_root, "latestSave.ini")


def resolve_active_save(
    save_root: Path,
    *,
    override: Path | None = None,
) -> ActiveSave:
    if override is not None:
        path = override.resolve()
        if not (path / "players.db").is_file():
            raise FileNotFoundError(f"players.db not found in override save: {path}")
        try:
            return _build(path, save_root, "explicit_override")
        except ValueError:
            return ActiveSave(
                path=path,
                game_mode=path.parent.name,
                folder_name=path.name,
                save_id=_identity(path.parent.name, path.name),
                selection_source="explicit_override",
            )

    selected = from_latest_save_ini(save_root)
    if selected is not None:
        return selected

    candidates = [db.parent for db in save_root.glob("*/*/players.db")]
    if not candidates:
        raise FileNotFoundError(f"No Project Zomboid saves below {save_root}")
    newest = max(candidates, key=lambda path: (path / "players.db").stat().st_mtime_ns)
    return _build(newest, save_root, "newest_players_db_fallback")


def activity_signature(save: ActiveSave) -> tuple[tuple[str, int, int], ...]:
    paths = [
        save.path / "players.db",
        save.path / "vehicles.db",
        save.path / "map_t.bin",
        latest_save_ini(save.path.parent.parent),
    ]
    result = []
    for path in paths:
        if path.is_file():
            stat = path.stat()
            result.append((path.name, stat.st_size, stat.st_mtime_ns))
    return tuple(result)

