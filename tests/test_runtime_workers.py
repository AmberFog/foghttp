import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
import warnings

import pytest

import foghttp
from foghttp._client.runtime.constants import RUNTIME_WORKERS_ENV
from foghttp.status_codes.success import OK


SHARED_RUNTIME_CLIENT_COUNT = 3
CONCURRENT_SHARED_RUNTIME_CLIENT_COUNT = 4


def test_client_accepts_explicit_runtime_workers() -> None:
    client = foghttp.Client(runtime_workers=1)
    client.close()


async def test_async_client_accepts_explicit_runtime_workers() -> None:
    client = foghttp.AsyncClient(runtime_workers=1)
    await client.aclose()


def test_client_accepts_explicit_shared_runtime() -> None:
    client = foghttp.Client(runtime="shared")
    client.close()


def test_client_accepts_explicit_dedicated_runtime() -> None:
    client = foghttp.Client(runtime="dedicated")
    client.close()


@pytest.mark.parametrize("runtime", ["default", "", "global", True])
def test_client_rejects_invalid_runtime(runtime: object) -> None:
    with pytest.raises(ValueError, match="runtime must be 'shared' or 'dedicated'"):
        foghttp.Client(runtime=runtime)  # type: ignore[arg-type]


def test_client_rejects_runtime_workers_with_shared_runtime() -> None:
    with pytest.raises(ValueError, match="runtime_workers requires runtime='dedicated'"):
        foghttp.Client(runtime="shared", runtime_workers=1)


@pytest.mark.parametrize("runtime_workers", [0, -1, 33, True, "2"])
def test_client_rejects_invalid_runtime_workers(runtime_workers: object) -> None:
    with pytest.raises(ValueError, match="runtime_workers must be an integer between 1 and 32"):
        foghttp.Client(runtime_workers=runtime_workers)  # type: ignore[arg-type]


def test_client_accepts_env_runtime_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(RUNTIME_WORKERS_ENV, "1")

    client = foghttp.Client()
    client.close()


def test_explicit_runtime_workers_override_invalid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(RUNTIME_WORKERS_ENV, "invalid")

    client = foghttp.Client(runtime_workers=1)
    client.close()


def test_explicit_shared_runtime_ignores_runtime_workers_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(RUNTIME_WORKERS_ENV, "invalid")

    client = foghttp.Client(runtime="shared")
    client.close()


def test_shared_runtime_survives_individual_sync_client_close(sync_http_server: str) -> None:
    for _ in range(SHARED_RUNTIME_CLIENT_COUNT):
        with foghttp.Client(runtime="shared") as client:
            response = client.get(sync_http_server)

        assert response.status_code == OK


async def test_shared_runtime_survives_individual_async_client_close(http_server: str) -> None:
    for _ in range(SHARED_RUNTIME_CLIENT_COUNT):
        async with foghttp.AsyncClient(runtime="shared") as client:
            response = await client.get(http_server)

        assert response.status_code == OK


def test_dedicated_runtime_without_workers_serves_sync_request(sync_http_server: str) -> None:
    with foghttp.Client(runtime="dedicated") as client:
        response = client.get(sync_http_server)

    assert response.status_code == OK


async def test_dedicated_runtime_without_workers_serves_async_request(http_server: str) -> None:
    async with foghttp.AsyncClient(runtime="dedicated") as client:
        response = await client.get(http_server)

    assert response.status_code == OK


def test_dedicated_close_does_not_stop_shared_sync_runtime(sync_http_server: str) -> None:
    with foghttp.Client(runtime="shared") as shared_client:
        assert shared_client.get(sync_http_server).status_code == OK

        with foghttp.Client(runtime="dedicated") as dedicated_client:
            assert dedicated_client.get(sync_http_server).status_code == OK

        assert shared_client.get(sync_http_server).status_code == OK


async def test_dedicated_close_does_not_stop_shared_async_runtime(http_server: str) -> None:
    async with foghttp.AsyncClient(runtime="shared") as shared_client:
        assert (await shared_client.get(http_server)).status_code == OK

        async with foghttp.AsyncClient(runtime="dedicated") as dedicated_client:
            assert (await dedicated_client.get(http_server)).status_code == OK

        assert (await shared_client.get(http_server)).status_code == OK


def test_shared_runtime_serves_concurrent_sync_clients(sync_http_server: str) -> None:
    barrier = threading.Barrier(CONCURRENT_SHARED_RUNTIME_CLIENT_COUNT)

    def send_request() -> int:
        with foghttp.Client(runtime="shared") as client:
            barrier.wait()
            return client.get(sync_http_server).status_code

    with ThreadPoolExecutor(max_workers=CONCURRENT_SHARED_RUNTIME_CLIENT_COUNT) as executor:
        futures = [executor.submit(send_request) for _index in range(CONCURRENT_SHARED_RUNTIME_CLIENT_COUNT)]
        results = [future.result() for future in futures]

    assert results == [OK] * CONCURRENT_SHARED_RUNTIME_CLIENT_COUNT


async def test_shared_runtime_serves_concurrent_async_clients(http_server: str) -> None:
    async def send_request() -> int:
        async with foghttp.AsyncClient(runtime="shared") as client:
            response = await client.get(http_server)
            return response.status_code

    results = await asyncio.gather(
        *(send_request() for _index in range(CONCURRENT_SHARED_RUNTIME_CLIENT_COUNT)),
    )

    assert results == [OK] * CONCURRENT_SHARED_RUNTIME_CLIENT_COUNT


@pytest.mark.parametrize("env_value", ["0", "33", "invalid", " 1", "+1"])
def test_client_rejects_invalid_env_runtime_workers(
    monkeypatch: pytest.MonkeyPatch,
    env_value: str,
) -> None:
    monkeypatch.setenv(RUNTIME_WORKERS_ENV, env_value)

    with (
        warnings.catch_warnings(record=True) as caught,
        pytest.raises(ValueError, match="FOGHTTP_RUNTIME_WORKERS must be an integer between 1 and 32"),
    ):
        foghttp.Client()

    assert not [item for item in caught if issubclass(item.category, foghttp.UnclosedClientError)]
