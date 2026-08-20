from pathlib import Path

from pzbot.active_save import resolve_active_save


def test_latest_save_ini_selects_active_save(tmp_path: Path):
    save_root = tmp_path / "Zomboid" / "Saves"
    first = save_root / "Apocalypse" / "first"
    second = save_root / "Sandbox" / "second"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "players.db").write_bytes(b"first")
    (second / "players.db").write_bytes(b"second")
    (save_root.parent / "latestSave.ini").write_text(
        "first\nApocalypse\n", encoding="utf-8"
    )
    active = resolve_active_save(save_root)
    assert active.path == first.resolve()
    assert active.selection_source == "latestSave.ini"

