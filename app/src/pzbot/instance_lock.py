"""Cross-platform non-blocking process lock for background monitors."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO


class InstanceAlreadyRunning(RuntimeError):
    """Raised when another relay process owns the instance lock."""


def _lock(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def single_instance(path: Path) -> Iterator[None]:
    """Hold an OS file lock until the monitor exits.

    The lock is released automatically even after a crash, unlike a PID-only
    sentinel. The file remains as harmless diagnostics containing the owner PID.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        try:
            _lock(handle)
        except OSError as exc:
            raise InstanceAlreadyRunning(str(path)) from exc

        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()).encode("ascii"))
        handle.flush()
        yield
    finally:
        try:
            _unlock(handle)
        except OSError:
            pass
        handle.close()
