import json
import subprocess
import sys

import pytest

from tests.client_upload.raw_callback_probe import (
    PROBE_SCENARIOS,
    PROBE_TIMEOUT,
    RAW_REQUEST_METHODS,
    REJECTED_SCENARIOS,
)


@pytest.mark.parametrize("request_method", RAW_REQUEST_METHODS)
@pytest.mark.parametrize("scenario", PROBE_SCENARIOS)
def test_raw_callback_capacity_admission_is_bounded_and_preserves_recovery(
    sync_http_server: str,
    request_method: str,
    scenario: str,
) -> None:
    try:
        result = subprocess.run(  # noqa: S603 - repository-owned bounded subprocess probe
            [
                sys.executable,
                "-m",
                "tests.client_upload.raw_callback_probe",
                request_method,
                scenario,
                sync_http_server,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT,
        )
    except subprocess.TimeoutExpired as error:
        pytest.fail(f"callback capacity wait exceeded watchdog: stdout={error.stdout!r}; stderr={error.stderr!r}")
    assert result.returncode == 0, result.stdout + result.stderr
    observation = json.loads(result.stdout)

    if scenario in REJECTED_SCENARIOS:
        assert observation["error_type"] == "FogHttpLifecycleError", observation
        assert "start_callback" in observation["error_message"], observation
        assert observation["stats_before_recovery"]["connections_opened"] == 0, observation
        assert observation["recovery_body"] == "r", observation
    else:
        assert observation["error_type"] is None, observation
        assert observation["response_body"] == "data", observation
    if scenario == "caught_send_final_byte":
        assert "callback_caught_capacity_error" in observation["events"], observation
        assert "callback_exit" in observation["events"], observation
    assert observation["worker_joined"] is True, observation
    assert observation["worker_error"] is None, observation
    assert observation["stats_after_recovery"]["active_requests"] == 0, observation
    assert observation["stats_after_recovery"]["pending_requests"] == 0, observation
