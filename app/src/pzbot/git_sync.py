"""Automatic direct-to-main publication of the sanitized live surface."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .settings import PublishSettings


class GitSync:
    def __init__(self, settings: PublishSettings):
        self.settings = settings

    def _run_git(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        # The background relay must never open an interactive credentials prompt.
        environment["GIT_TERMINAL_PROMPT"] = "0"
        environment["GCM_INTERACTIVE"] = "Never"
        try:
            return subprocess.run(
                command,
                cwd=self.settings.repository_path,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=90,
                env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"git command timed out after {exc.timeout} seconds: {' '.join(command)}"
            ) from exc

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = self._run_git(["git", *args])
        error_text = f"{result.stderr}\n{result.stdout}".lower()

        # Git for Windows can occasionally fail its Schannel TLS handshake even
        # though the same host works through Git's bundled OpenSSL backend.
        if result.returncode and "schannel" in error_text:
            result = self._run_git(
                ["git", "-c", "http.sslBackend=openssl", *args]
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

        live_paths = (
            "live/current_state.json",
            "live/chatgpt_state.json",
            "live/changes.jsonl",
            "live/status.json",
        )
        missing = [
            str(repository / path)
            for path in live_paths
            if not (repository / path).is_file()
        ]
        if missing:
            raise RuntimeError(f"Live files missing before publish: {missing}")

        self._git("add", "--", *live_paths)
        if self._git("diff", "--cached", "--quiet", "--", *live_paths, check=False).returncode == 0:
            return "unchanged"

        # --only guarantees that unrelated staged development files can never
        # leak into an automatic telemetry commit.
        self._git(
            "commit",
            "-m",
            f"Live sync: {save_name} at {updated_at}",
            "--only",
            "--",
            *live_paths,
        )
        self._git(
            "push",
            self.settings.remote,
            f"HEAD:{self.settings.branch}",
        )
        return "published"
