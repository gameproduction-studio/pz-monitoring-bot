from __future__ import annotations

import subprocess

from pzbot.git_sync import GitSync
from pzbot.settings import PublishSettings


def publish_settings(tmp_path):
    return PublishSettings(
        enabled=True,
        repository_path=tmp_path,
        remote="origin",
        branch="main",
        minimum_interval_seconds=0,
    )


def completed(command, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


def test_schannel_failure_retries_with_openssl(tmp_path, monkeypatch):
    sync = GitSync(publish_settings(tmp_path))
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if len(calls) == 1:
            return completed(command, 1, stderr="schannel: failed to receive handshake")
        return completed(command)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = sync._git("push", "origin", "HEAD:main")

    assert result.returncode == 0
    assert calls[0][0] == ["git", "push", "origin", "HEAD:main"]
    assert calls[1][0] == [
        "git",
        "-c",
        "http.sslBackend=openssl",
        "push",
        "origin",
        "HEAD:main",
    ]
    assert calls[0][1]["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert calls[0][1]["env"]["GCM_INTERACTIVE"] == "Never"
    assert calls[0][1]["timeout"] == 90


def test_publish_commit_is_limited_to_live_files(tmp_path):
    (tmp_path / ".git").mkdir()
    live = tmp_path / "live"
    live.mkdir()
    for name in (
        "current_state.json",
        "chatgpt_state.json",
        "changes.jsonl",
        "status.json",
    ):
        (live / name).write_text("test", encoding="utf-8")
    chatgpt = live / "chatgpt"
    chatgpt.mkdir()
    (chatgpt / "manifest.json").write_text("test", encoding="utf-8")

    sync = GitSync(publish_settings(tmp_path))
    calls = []

    def fake_git(*args, check=True):
        calls.append(args)
        if args[:3] == ("diff", "--cached", "--quiet"):
            return completed(list(args), returncode=1)
        return completed(list(args))

    sync._git = fake_git
    assert sync.publish_if_dirty(save_name="Test", updated_at="now") == "published"

    commit = next(args for args in calls if args and args[0] == "commit")
    assert "--only" in commit
    assert commit[-2:] == ("live/chatgpt_state.json", "live/chatgpt")
    add = next(args for args in calls if args and args[0] == "add")
    assert add[:3] == ("add", "-A", "--")
    assert calls[-1] == ("push", "origin", "HEAD:main")


def test_telemetry_waits_for_stable_pair(tmp_path, monkeypatch):
    from pzbot import cli

    settings = settings_for_stability(tmp_path)
    first = (("pzmb_current_state.json", 100, 1), ("pzmb_status.json", 20, 1))
    changed = (("pzmb_current_state.json", 120, 2), ("pzmb_status.json", 20, 1))
    signatures = iter((first, changed, changed, changed))

    monkeypatch.setattr(cli, "_telemetry_signature", lambda _settings: next(signatures))
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: None)

    assert cli._stable_telemetry_signature(settings) == changed


def settings_for_stability(tmp_path):
    from types import SimpleNamespace

    return SimpleNamespace(
        telemetry_dir=tmp_path,
        stable_polls=3,
        stable_interval_seconds=0,
    )
