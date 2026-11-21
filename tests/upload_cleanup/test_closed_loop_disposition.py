import json
import subprocess
import sys

from .constants import CALLBACK_WATCHDOG, CHAIN_OBLIGATIONS


def test_pending_async_cleanup_on_closed_loop_retains_bounded_stalled_obligation() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tests.upload_cleanup.closed_loop_probe"],
        check=False,
        capture_output=True,
        text=True,
        timeout=CALLBACK_WATCHDOG,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    observation = json.loads(result.stdout)

    assert observation["before_release"]["reserved"] == CHAIN_OBLIGATIONS
    assert observation["before_release"]["active"] == 1
    assert observation["before_release"]["pending"] == 1
    assert observation["after_release"]["reserved"] == 1
    assert observation["after_release"]["stalled"] == 1
    assert observation["after_loop_switch"]["reserved"] == 1
    assert observation["after_loop_switch"]["stalled"] == 1
    assert observation["async_close_calls"] == 0
    assert observation["oversized_admission_rejected"] is True
    assert observation["sync_recovery_calls"] == 1
    assert observation["final_snapshot"]["reserved"] == 1
    assert observation["final_snapshot"]["active"] == 0
    assert observation["final_snapshot"]["pending"] == 0
    assert observation["final_snapshot"]["stalled"] == 1
