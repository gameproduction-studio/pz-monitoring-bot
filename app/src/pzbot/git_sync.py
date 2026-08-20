"""Automatic direct-to-main publication of the sanitized live surface."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .settings import PublishSettings


class GitSync:
    def __init__(self, settings: PublishSettings):
        self.settings = settings

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args],
            cwd=self.settings.repository_path,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )
        if check and result.returncode:
            raise RuntimeError(
                f"git {' '.join(args)} failed: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        return result

    def publish_if_dirty(self, *, save_name: str, updated_at: str) -> str:
        if not self.settings.enabled:
            return "disabled"
        repository = self.settings.repository_path
        if not (repository / ".git").is_dir():
            raise RuntimeError(f"Not a Git repository: {repository}")
        live = repository / "live"
        expected = [
            live / "current_state.json",
            live / "changes.jsonl",
            live / "status.json",
        ]
        missing = [str(path) for path in expected if not path.is_file()]
        if missing:
            raise RuntimeError(f"Live files missing before publish: {missing}")

        self._git(
            "add",
            "--",
            "live/current_state.json",
            "live/changes.jsonl",
            "live/status.json",
        )
        if self._git("diff", "--cached", "--quiet", check=False).returncode == 0:
            return "unchanged"

        self._git(
            "commit",
            "-m",
            f"Live sync: {save_name} at {updated_at}",
        )
        self._git(
            "push",
            self.settings.remote,
            f"HEAD:{self.settings.branch}",
        )
        return "published"

