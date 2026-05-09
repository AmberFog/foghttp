import warnings

import pytest

import foghttp
from foghttp._client.runtime.constants import RUNTIME_WORKERS_ENV


def test_client_accepts_explicit_runtime_workers() -> None:
    client = foghttp.Client(runtime_workers=1)
    client.close()


async def test_async_client_accepts_explicit_runtime_workers() -> None:
    client = foghttp.AsyncClient(runtime_workers=1)
    await client.aclose()


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
