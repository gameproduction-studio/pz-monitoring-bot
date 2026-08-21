from __future__ import annotations

import pytest

from pzbot.instance_lock import InstanceAlreadyRunning, single_instance


def test_single_instance_rejects_second_relay(tmp_path):
    lock_path = tmp_path / "relay-monitor.lock"

    with single_instance(lock_path):
        with pytest.raises(InstanceAlreadyRunning):
            with single_instance(lock_path):
                pass

    with single_instance(lock_path):
        pass
    assert int(lock_path.read_text(encoding="ascii")) > 0
