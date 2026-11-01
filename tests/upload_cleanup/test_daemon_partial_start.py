from unittest.mock import Mock

import pytest

from foghttp._upload_body.thread_bridge import start_daemon_worker

from .constants import COMPLETION_WATCHDOG
from .partial_start_actions import PartialWorkerStart


@pytest.mark.parametrize(
    ("capture_start_error", "failure", "captured"),
    [
        pytest.param(False, RuntimeError("rejected daemon startup"), False, id="propagated-error"),
        pytest.param(True, RuntimeError("captured daemon startup"), True, id="captured-error"),
        pytest.param(True, GeneratorExit("control startup failure"), False, id="control-error"),
    ],
)
def test_partial_daemon_start_never_runs_rejected_callback_and_recovers(
    monkeypatch: pytest.MonkeyPatch,
    *,
    capture_start_error: bool,
    failure: BaseException,
    captured: bool,
) -> None:
    callback = Mock(return_value="rejected callback")
    fault = PartialWorkerStart("daemon", failure)
    try:
        with monkeypatch.context() as startup:
            fault.install(startup)
            if captured:
                completion = start_daemon_worker(callback, capture_start_error=capture_start_error)
                with pytest.raises(type(failure)) as observed:
                    completion.result(timeout=COMPLETION_WATCHDOG)
            else:
                with pytest.raises(type(failure)) as observed:
                    start_daemon_worker(callback, capture_start_error=capture_start_error)
        assert observed.value is failure
        assert fault.entered.is_set()
        callback.assert_not_called()
    finally:
        stopped = fault.finish()

    assert stopped is True
    assert fault.finished.is_set()
    callback.assert_not_called()
    recovery = start_daemon_worker(lambda: "healthy callback")
    assert recovery.result(timeout=COMPLETION_WATCHDOG) == "healthy callback"
