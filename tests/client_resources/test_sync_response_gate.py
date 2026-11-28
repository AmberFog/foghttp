from concurrent.futures import ThreadPoolExecutor

import pytest

import foghttp
from foghttp.status_codes.success import OK

from .constants import SLOW_RESPONSE_PATH
from .gates import SyncResponseGate
from .helpers import wait_for_sync_stats


def test_assertion_failure_releases_only_the_held_origin(
    sync_resource_http_server: str,
    secondary_sync_resource_http_server: str,
    sync_resource_gate: SyncResponseGate,
    secondary_sync_resource_gate: SyncResponseGate,
) -> None:
    with (
        foghttp.Client(timeouts=foghttp.Timeouts(total=5.0)) as client,
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        secondary = executor.submit(client.get, secondary_sync_resource_http_server + SLOW_RESPONSE_PATH)
        with secondary_sync_resource_gate.hold():
            wait_for_sync_stats(client, lambda stats: stats.active_requests == 1)
            assert not sync_resource_gate.request_started.is_set()
            primary = executor.submit(client.get, sync_resource_http_server + SLOW_RESPONSE_PATH)
            with pytest.raises(AssertionError, match="primary response is held"), sync_resource_gate.hold():
                assert primary.done(), "primary response is held"

            assert primary.result(timeout=1.0).status_code == OK
            assert not secondary_sync_resource_gate.release_response.is_set()
            assert not secondary.done()
            state = client.dump_transport_state()
            assert state["origins"][secondary_sync_resource_http_server]["active_requests"] == 1

        assert secondary.result(timeout=1.0).status_code == OK
        assert client.stats().active_requests == 0
