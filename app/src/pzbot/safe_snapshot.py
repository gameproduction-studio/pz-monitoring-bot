"""Consistent, read-only snapshots of a live Project Zomboid save."""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import quote


FIXED_FILES = (
    "WorldDictionaryReadable.lua",
    "recorded_media.bin",
    "map_ver.bin",
    "map_t.bin",
)


def _source_files(save_dir: Path) -> list[Path]:
    paths = [
        save_dir / name
        for name in (*FIXED_FILES, "players.db", "vehicles.db")
        if (save_dir / name).is_file()
    ]
    paths.extend(sorted((save_dir / "map").glob("*/*.bin")))
    return paths


def source_fingerprint(save_dir: Path) -> tuple[tuple[str, int, int], ...]:
    records = []
    for path in _source_files(save_dir):
        stat = path.stat()
        records.append(
            (
                path.relative_to(save_dir).as_posix(),
                stat.st_size,
                stat.st_mtime_ns,
            )
        )
    return tuple(records)


def _sqlite_backup_read_only(source: Path, destination: Path) -> None:
    uri = "file:" + quote(source.resolve().as_posix()) + "?mode=ro"
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(uri, uri=True, timeout=15)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.execute("PRAGMA query_only=ON")
        source_connection.backup(destination_connection)
        destination_connection.commit()
    finally:
        destination_connection.close()
        source_connection.close()


def _copy_once(save_dir: Path, destination: Path) -> None:
    for name in FIXED_FILES:
        source = save_dir / name
        if source.is_file():
            shutil.copy2(source, destination / name)

    for name in ("players.db", "vehicles.db"):
        source = save_dir / name
        if source.is_file():
            _sqlite_backup_read_only(source, destination / name)

    for source in sorted((save_dir / "map").glob("*/*.bin")):
        target = destination / source.relative_to(save_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


@contextmanager
def safe_save_snapshot(
    save_dir: Path,
    runtime_dir: Path,
    *,
    attempts: int = 5,
    retry_seconds: float = 1.0,
) -> Iterator[Path]:
    """Yield a private copy only when source metadata is unchanged end-to-end."""
    runtime_dir.mkdir(parents=True, exist_ok=True)
    last_before: tuple[tuple[str, int, int], ...] | None = None
    last_after: tuple[tuple[str, int, int], ...] | None = None

    for _ in range(attempts):
        temporary = tempfile.TemporaryDirectory(prefix="pzbot-save-", dir=runtime_dir)
        snapshot = Path(temporary.name)
        try:
            last_before = source_fingerprint(save_dir)
            _copy_once(save_dir, snapshot)
            last_after = source_fingerprint(save_dir)
            if last_before == last_after:
                try:
                    yield snapshot
                finally:
                    temporary.cleanup()
                return
        except Exception:
            temporary.cleanup()
            raise
        temporary.cleanup()
        time.sleep(retry_seconds)

    raise TimeoutError(
        "The Project Zomboid save kept changing during snapshot creation; "
        f"before={last_before!r} after={last_after!r}"
    )

