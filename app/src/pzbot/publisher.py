from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from .config import PublishConfig
from .jsonio import atomic_write_json


class GitPublisher:
    def __init__(self, config: PublishConfig):
        self.config = config
        self._last_publish = 0.0

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args], cwd=self.config.repository_path, text=True,
            encoding="utf-8", errors="replace", capture_output=True,
        )
        if check and result.returncode:
            raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result

    def publish(self, state: dict[str, Any], changes: list[dict[str, Any]], *, force: bool = False) -> str:
        if not self.config.enabled:
            return "disabled"
        elapsed = time.monotonic() - self._last_publish
        if not force and elapsed < self.config.minimum_interval_seconds:
            return "debounced"
        repository = self.config.repository_path
        if not (repository / ".git").exists():
            raise RuntimeError(f"Not a Git repository: {repository}")
        public = repository / "public"
        atomic_write_json(public / "current_state.json", state)
        atomic_write_json(public / "changes.json", {"schema": "project-the-bot-monitoring/changes/v1", "changes": changes[-200:]})
        self._git("add", "--", "public/current_state.json", "public/changes.json")
        if self._git("diff", "--cached", "--quiet", check=False).returncode == 0:
            return "unchanged"
        summary = state["summary"]
        message = f"Update inventory: {summary['physicalItems']} items, {summary['eventCount']} changes"
        self._git("commit", "-m", message)
        self._git("push", self.config.remote, f"HEAD:{self.config.branch}")
        self._last_publish = time.monotonic()
        return "published"

