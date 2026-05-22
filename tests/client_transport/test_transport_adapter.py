from typing import NoReturn

from faker import Faker
import pytest

from foghttp._client.transport import RawAsyncTransport, RawSyncTransport
from foghttp._request_body import request_body
from foghttp.methods import GET, POST
from foghttp.request import Request
from foghttp.timeouts import Timeouts
from tests.request_factories import non_replayable_request

from .models import (
    AsyncRecordingTransport,
    AsyncTransportClient,
    SyncRecordingTransport,
    SyncTransportClient,
    TransportCall,
    response_for_request,
)


def test_sync_send_uses_transport_adapter_without_opening_raw_client(
    faker: Faker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("foghttp._client.core.create_raw_client", _fail_create_raw_client)
    client_timeouts = Timeouts(total=7.5)
    request = Request(GET, faker.url())
    response = response_for_request(request)
    transport = SyncRecordingTransport(response=response)

    with SyncTransportClient(transport=transport, timeouts=client_timeouts) as client:
        result = client.send(request)

    assert result is response
    assert transport.calls == [TransportCall(request=request, timeouts=client_timeouts)]


async def test_async_send_uses_transport_adapter_without_opening_raw_client(
    faker: Faker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("foghttp._client.core.create_raw_client", _fail_create_raw_client)
    client_timeouts = Timeouts(total=7.5)
    request = Request(GET, faker.url())
    response = response_for_request(request)
    transport = AsyncRecordingTransport(response=response)

    async with AsyncTransportClient(transport=transport, timeouts=client_timeouts) as client:
        result = await client.send(request)

    assert result is response
    assert transport.calls == [TransportCall(request=request, timeouts=client_timeouts)]


def test_raw_sync_transport_sends_prepared_request_through_raw_client(
    faker: Faker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_request: dict[str, object] = {}
    raw_client = object()
    raw_response = object()
    request = non_replayable_request(
        POST,
        faker.url(),
        headers=[("X-Trace", faker.uuid4())],
        content=faker.binary(length=8),
    )
    response = response_for_request(request)
    timeouts = Timeouts(pool=0.5, total=2.0)
    body = request_body(request)

    def fake_send_raw_request(**kwargs: object) -> object:
        captured_request.update(kwargs)
        return raw_response

    def fake_response_from_raw(**kwargs: object) -> object:
        assert kwargs["raw"] is raw_response
        assert isinstance(kwargs["started"], float)
        return response

    monkeypatch.setattr("foghttp._client.transport.send_raw_request", fake_send_raw_request)
    monkeypatch.setattr("foghttp._client.transport.response_from_raw", fake_response_from_raw)

    result = RawSyncTransport(lambda: raw_client).send(request, timeouts=timeouts)

    assert result is response
    assert captured_request == {
        "raw_client": raw_client,
        "method": request.method,
        "url": request.url,
        "headers": request.headers.multi_items(),
        "body": body.content,
        "body_replayable": body.replayable,
        "timeouts": timeouts,
    }


async def test_raw_async_transport_sends_prepared_request_through_raw_client(
    faker: Faker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_request: dict[str, object] = {}
    raw_client = object()
    raw_response = object()
    request = Request(POST, faker.url(), headers=[("X-Trace", faker.uuid4())], content=faker.binary(length=8))
    response = response_for_request(request)
    timeouts = Timeouts(pool=0.5, total=2.0)
    body = request_body(request)

    async def fake_send_raw_request_async(**kwargs: object) -> object:
        captured_request.update(kwargs)
        return raw_response

    def fake_response_from_raw(**kwargs: object) -> object:
        assert kwargs["raw"] is raw_response
        assert isinstance(kwargs["started"], float)
        return response

    monkeypatch.setattr("foghttp._client.transport.send_raw_request_async", fake_send_raw_request_async)
    monkeypatch.setattr("foghttp._client.transport.response_from_raw", fake_response_from_raw)

    result = await RawAsyncTransport(lambda: raw_client).send(request, timeouts=timeouts)

    assert result is response
    assert captured_request == {
        "raw_client": raw_client,
        "method": request.method,
        "url": request.url,
        "headers": request.headers.multi_items(),
        "body": body.content,
        "body_replayable": body.replayable,
        "timeouts": timeouts,
    }


def _fail_create_raw_client(**_kwargs: object) -> NoReturn:
    msg = "raw client should not be created when a test transport is installed"
    raise AssertionError(msg)
