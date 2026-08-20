from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


class ScannerAdapter:
    def __init__(self, game_path: Path):
        self.game_path = game_path

    def scan(self, save_path: Path) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="pzbot-scan-") as temporary:
            output = Path(temporary) / "snapshot.json"
            log = Path(temporary) / "scanner.log"
            result = subprocess.run(
                [sys.executable, "-m", "pzbot.pz_save_scanner", "--save", str(save_path), "--game", str(self.game_path), "--output", str(output), "--log", str(log)],
                text=True, encoding="utf-8", errors="replace", capture_output=True,
            )
            if result.returncode:
                details = log.read_text(encoding="utf-8", errors="replace") if log.exists() else result.stderr
                raise RuntimeError(f"Inventory scanner failed: {details[-4000:]}")
            snapshot = json.loads(output.read_text(encoding="utf-8-sig"))
            if snapshot.get("readOnly") is not True:
                raise RuntimeError("Scanner did not confirm read-only mode")
            return snapshot

