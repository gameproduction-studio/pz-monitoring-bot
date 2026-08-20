from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from pzbot.safe_snapshot import safe_save_snapshot, source_fingerprint


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_snapshot_uses_sqlite_backup_and_does_not_change_source(tmp_path: Path):
    save = tmp_path / "save"
    runtime = tmp_path / "runtime"
    save.mkdir()
    database = save / "players.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE test(value TEXT)")
        connection.execute("INSERT INTO test(value) VALUES('unchanged')")
    (save / "WorldDictionaryReadable.lua").write_text("dictionary", encoding="utf-8")
    chunk = save / "map" / "1" / "2.bin"
    chunk.parent.mkdir(parents=True)
    chunk.write_bytes(b"chunk-data")

    before_fingerprint = source_fingerprint(save)
    before_hash = digest(database)
    with safe_save_snapshot(save, runtime) as copied:
        assert (copied / "players.db").is_file()
        assert (copied / "map" / "1" / "2.bin").read_bytes() == b"chunk-data"
        connection = sqlite3.connect(copied / "players.db")
        try:
            assert connection.execute("SELECT value FROM test").fetchone()[0] == "unchanged"
        finally:
            connection.close()

    assert source_fingerprint(save) == before_fingerprint
    assert digest(database) == before_hash

