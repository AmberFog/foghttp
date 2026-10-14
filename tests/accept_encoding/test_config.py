from typing import cast

import pytest

import foghttp
from tests.client_telemetry.models import RecordingTelemetrySink


@pytest.mark.parametrize("client_type", [foghttp.Client, foghttp.AsyncClient])
@pytest.mark.parametrize("invalid", [None, 0, 1, "true"])
def test_client_requires_real_boolean(client_type: type[foghttp.Client | foghttp.AsyncClient], invalid: object) -> None:
    with pytest.raises(TypeError, match="auto_accept_encoding must be a bool"):
        client_type(auto_accept_encoding=cast("bool", invalid))


@pytest.mark.parametrize("invalid", [0, 1, "true"])
def test_request_validates_before_body_normalization(invalid: object) -> None:
    with pytest.raises(TypeError, match="auto_accept_encoding must be a bool"):
        foghttp.Request(
            "POST",
            "https://example.invalid",
            content=object(),
            auto_accept_encoding=cast("bool", invalid),
        )


@pytest.mark.parametrize("default", [False, True])
@pytest.mark.parametrize("override", [None, False, True])
def test_builder_snapshots_setting_without_injecting_header(*, default: bool, override: bool | None) -> None:
    with foghttp.Client(auto_accept_encoding=default) as client:
        request = client.build_request("GET", "https://example.invalid", auto_accept_encoding=override)

    expected = default if override is None else override
    assert request.auto_accept_encoding is expected
    assert "Accept-Encoding" not in request.headers


def test_direct_request_setting_is_deferred_and_read_only() -> None:
    request = foghttp.Request("GET", "https://example.invalid")
    assert request.auto_accept_encoding is None
    with pytest.raises(AttributeError):
        setattr(request, "auto_accept_encoding", True)  # noqa: B010


@pytest.mark.parametrize("invalid", [0, 1, "true"])
@pytest.mark.parametrize("method", ["request", "build_request", "stream"])
def test_invalid_override_precedes_body_encoding(method: str, invalid: object) -> None:
    with foghttp.Client() as client, pytest.raises(TypeError, match="auto_accept_encoding must be a bool"):
        getattr(client, method)("POST", "https://example.invalid", json=object(), auto_accept_encoding=invalid)


@pytest.mark.parametrize("invalid", [0, 1, "true"])
async def test_async_invalid_override_precedes_body_encoding(invalid: object) -> None:
    async with foghttp.AsyncClient() as client:
        with pytest.raises(TypeError, match="auto_accept_encoding must be a bool"):
            await client.post("https://example.invalid", json=object(), auto_accept_encoding=cast("bool", invalid))
        with pytest.raises(TypeError, match="auto_accept_encoding must be a bool"):
            client.stream("POST", "https://example.invalid", json=object(), auto_accept_encoding=cast("bool", invalid))


@pytest.mark.parametrize("invalid", [0, 1, "true"])
def test_invalid_send_override_has_no_telemetry_or_network_side_effect(invalid: object) -> None:
    sink = RecordingTelemetrySink()
    request = foghttp.Request("GET", "https://example.invalid")
    with foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=sink)) as client:
        with pytest.raises(TypeError, match="auto_accept_encoding must be a bool"):
            client.send(request, auto_accept_encoding=cast("bool", invalid))
        assert client.stats().total_requests == 0
        assert not sink.events


@pytest.mark.parametrize("invalid", [0, 1, "true"])
async def test_async_invalid_send_override_has_no_side_effect(invalid: object) -> None:
    sink = RecordingTelemetrySink()
    request = foghttp.Request("GET", "https://example.invalid")
    async with foghttp.AsyncClient(telemetry=foghttp.TelemetryConfig(sink=sink)) as client:
        with pytest.raises(TypeError, match="auto_accept_encoding must be a bool"):
            await client.send(request, auto_accept_encoding=cast("bool", invalid))
        assert client.stats().total_requests == 0
        assert not sink.events
