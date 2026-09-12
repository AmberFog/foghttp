from collections.abc import Callable
import gc
from typing import Never
import warnings

from faker import Faker
import pytest

import foghttp
from foghttp._client.lifecycle_debug import AsyncLifecycleDebugTracker

from .helpers import CloseTrackingRawClient, RawClientFactory


@pytest.mark.usefixtures("sync_noop_transport")
def test_sync_client_does_not_require_async_lifecycle_tracker(
    monkeypatch: pytest.MonkeyPatch,
    construction_failure: Callable[..., Never],
    sync_client_factory: type[foghttp.Client],
    raw_client: CloseTrackingRawClient,
    raw_client_factory: RawClientFactory,
    faker: Faker,
) -> None:
    monkeypatch.setattr(AsyncLifecycleDebugTracker, "__init__", construction_failure)

    with sync_client_factory() as client:
        client.get(faker.url())

    assert raw_client_factory.calls == 1
    assert raw_client.close_calls == 1


@pytest.mark.parametrize(
    ("failure_target", "expected_warnings"),
    [
        pytest.param("foghttp._client.config.ClientConfig.from_options", 0, id="config"),
        pytest.param("foghttp._client.lifecycle_debug.AsyncLifecycleDebugTracker.__init__", 0, id="tracker"),
        pytest.param("foghttp._client.core.TelemetryDispatcher.__init__", 1, id="base"),
        pytest.param("foghttp.AsyncClient._create_transport", 1, id="adapter"),
    ],
)
@pytest.mark.parametrize(
    "debug_config",
    [
        pytest.param(None, id="disabled"),
        pytest.param(foghttp.AsyncLifecycleDebugConfig(), id="enabled"),
        pytest.param(foghttp.AsyncLifecycleDebugConfig(strict=True), id="strict"),
    ],
)
def test_async_construction_failure_preserves_error_without_finalizer_error(
    monkeypatch: pytest.MonkeyPatch,
    construction_failure: Callable[..., Never],
    unraisable_errors: list[str],
    failure_target: str,
    expected_warnings: int,
    debug_config: foghttp.AsyncLifecycleDebugConfig | None,
) -> None:
    monkeypatch.setattr(failure_target, construction_failure)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", foghttp.UnclosedClientError)
        with pytest.raises(RuntimeError, match=r"^client construction failed$"):
            foghttp.AsyncClient(lifecycle_debug=debug_config)
        gc.collect()

    assert unraisable_errors == []
    assert len(caught) == expected_warnings
    assert all(warning.category is foghttp.UnclosedClientError for warning in caught)
