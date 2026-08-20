from __future__ import annotations

import hashlib
import time
from pathlib import Path


def newest_save(save_root: Path) -> Path:
    candidates = [players.parent for players in save_root.glob("*/*/players.db")]
    if not candidates:
        raise FileNotFoundError(f"No Project Zomboid players.db below {save_root}")
    return max(candidates, key=lambda directory: (directory / "players.db").stat().st_mtime_ns)


def signature(path: Path) -> str:
    stat = path.stat()
    material = f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}".encode()
    return hashlib.sha256(material).hexdigest()


def wait_stable(path: Path, polls: int, interval: float, timeout: float = 90) -> str:
    deadline = time.monotonic() + timeout
    previous = None
    stable = 0
    while time.monotonic() < deadline:
        current = (path.stat().st_size, path.stat().st_mtime_ns)
        stable = stable + 1 if current == previous else 1
        previous = current
        if stable >= polls:
            return signature(path)
        time.sleep(interval)
    raise TimeoutError(f"Save did not stabilize: {path}")

