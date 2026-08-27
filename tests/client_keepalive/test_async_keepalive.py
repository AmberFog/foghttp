from collections.abc import AsyncIterator
from functools import partial
from io import BytesIO
import json

import pytest

import foghttp
from foghttp.methods import GET
from foghttp.status_codes.redirect import PERMANENT_REDIRECT, TEMPORARY_REDIRECT
from foghttp.status_codes.success import OK
from tests.client_multipart.sources import (
    AsyncChunks,
    ClosingBytesFile,
    FailsWhenReadPastExactLengthFile,
    TrackedFactory,
)
from tests.client_upload.helpers import DelayedCloseEmptyFile, MisreportedLengthFile
from tests.support.transport_state import wait_for_async_transport_state
from tests.support.transport_stats import wait_for_async_transport_stats

from .assertions import (
    assert_distinct_connection_payloads,
    assert_distinct_connection_snapshot,
    assert_redirect_preserved_request,
    assert_request_payloads,
    assert_reused_connection_payloads,
    assert_reused_connection_snapshot,
    assert_reused_connection_stats,
    assert_single_connection_snapshot,
    has_idle_origin_detail,
    is_early_remote_idle_close_observed,
    is_idle_timeout_eviction_reported,
)
from .constants import (
    EXPECTED_DISTINCT_CONNECTIONS,
    EXPECTED_REUSED_CONNECTIONS,
    KEEPALIVE_PATH,
    REDIRECT_PATH_PREFIX,
)
from .server import KeepAliveServer


IDLE_TIMEOUT_SECONDS = 0.05
JSON_REQUEST_COUNT = 6
LONG_IDLE_TIMEOUT_SECONDS = 30.0
BODY_MATRIX_REQUEST_COUNT = 5
CHUNKED_BODY = b"chunked-body"
KNOWN_LENGTH_REQUEST_COUNT = 2
REDIRECT_REQUEST_COUNT = 2
REDIRECT_REQUEST_BODY = b"redirect-body"
MULTIPART_REQUEST_BODY = b"multipart-body"
METHOD_PRESERVING_REDIRECTS = (
    pytest.param(TEMPORARY_REDIRECT, id="307-temporary"),
    pytest.param(PERMANENT_REDIRECT, id="308-permanent"),
)
MISREPORTED_LENGTH_CASES = (
    pytest.param(b"short", 6, False, id="short"),
    pytest.param(b"oversized", 8, True, id="oversized"),
)


async def test_async_client_reuses_keepalive_connection(keepalive_http_server: KeepAliveServer) -> None:
    limits = foghttp.Limits(
        keepalive=True,
        max_idle_connections_per_host=EXPECTED_REUSED_CONNECTIONS,
    )

    async with foghttp.AsyncClient(limits=limits) as client:
        first_response = await client.get(keepalive_http_server.url + KEEPALIVE_PATH)
        second_response = await client.get(keepalive_http_server.url + KEEPALIVE_PATH)

    assert first_response.status_code == OK
    assert second_response.status_code == OK
    assert_reused_connection_payloads(first_response.json(), second_response.json())
    assert_reused_connection_snapshot(keepalive_http_server.snapshot())


async def test_async_stream_reuses_keepalive_connection_after_clean_eof(
    keepalive_http_server: KeepAliveServer,
) -> None:
    limits = foghttp.Limits(
        keepalive=True,
        max_idle_connections_per_host=EXPECTED_REUSED_CONNECTIONS,
    )
    url = keepalive_http_server.url + KEEPALIVE_PATH

    async with (
        foghttp.AsyncClient(limits=limits) as client,
        client.stream(GET, url) as first_response,
    ):
        first_payload = json.loads(b"".join([chunk async for chunk in first_response.aiter_bytes()]))
        second_response = await client.get(url)

    assert first_response.status_code == OK
    assert second_response.status_code == OK
    assert_reused_connection_payloads(first_payload, second_response.json())
    assert_reused_connection_snapshot(keepalive_http_server.snapshot())


async def test_async_client_does_not_reuse_connection_when_keepalive_is_disabled(
    keepalive_http_server: KeepAliveServer,
) -> None:
    limits = foghttp.Limits(keepalive=False)

    async with foghttp.AsyncClient(limits=limits) as client:
        first_response = await client.get(keepalive_http_server.url + KEEPALIVE_PATH)
        second_response = await client.get(keepalive_http_server.url + KEEPALIVE_PATH)

    assert first_response.status_code == OK
    assert second_response.status_code == OK
    assert_distinct_connection_payloads(first_response.json(), second_response.json())
    assert_distinct_connection_snapshot(keepalive_http_server.snapshot())


async def test_async_json_request_bodies_reuse_one_connection(
    keepalive_http_server: KeepAliveServer,
) -> None:
    limits = foghttp.Limits(keepalive=True, max_idle_connections_per_host=1)
    url = keepalive_http_server.url + KEEPALIVE_PATH

    async with foghttp.AsyncClient(limits=limits) as client:
        responses = []
        for request_index in range(JSON_REQUEST_COUNT):
            response = await client.post(url, json={"request_index": request_index})
            if request_index == 0:
                response.json()
            responses.append(response)
        stats = client.stats()

    assert all(response.status_code == OK for response in responses)
    assert_reused_connection_stats(stats, JSON_REQUEST_COUNT)
    assert_single_connection_snapshot(keepalive_http_server.snapshot(), JSON_REQUEST_COUNT)


async def test_async_body_variants_reuse_one_connection(
    keepalive_http_server: KeepAliveServer,
) -> None:
    limits = foghttp.Limits(keepalive=True, max_idle_connections_per_host=1)
    url = keepalive_http_server.url + KEEPALIVE_PATH

    async with foghttp.AsyncClient(limits=limits) as client:
        responses = (
            await client.post(url, content=b"raw-body"),
            await client.post(url, json={"body": "json"}),
            await client.post(url, data={"body": "form"}),
            await client.put(url, content=BytesIO(b"streaming-body")),
            await client.patch(url, content=_chunked_body()),
        )
        stats = client.stats()

    assert all(response.status_code == OK for response in responses)
    assert_request_payloads(
        responses,
        (
            ("POST", b"raw-body"),
            ("POST", b'{"body":"json"}'),
            ("POST", b"body=form"),
            ("PUT", b"streaming-body"),
            ("PATCH", CHUNKED_BODY),
        ),
    )
    assert_reused_connection_stats(stats, BODY_MATRIX_REQUEST_COUNT)
    assert_single_connection_snapshot(keepalive_http_server.snapshot(), BODY_MATRIX_REQUEST_COUNT)


async def test_async_multipart_file_upload_reuses_connection(
    keepalive_http_server: KeepAliveServer,
) -> None:
    content = ClosingBytesFile(MULTIPART_REQUEST_BODY)
    url = keepalive_http_server.url + KEEPALIVE_PATH

    async with foghttp.AsyncClient() as client:
        first_response = await client.post(url, files={"file": ("payload.bin", content)})
        second_response = await client.get(url)
        stats = client.stats()

    assert first_response.status_code == OK
    assert second_response.status_code == OK
    assert_reused_connection_stats(stats, KNOWN_LENGTH_REQUEST_COUNT)
    assert_single_connection_snapshot(keepalive_http_server.snapshot(), KNOWN_LENGTH_REQUEST_COUNT)
    assert content.closed is False
    assert content.close_calls == 0
    content.close()


async def test_async_known_length_upload_finishes_without_reading_past_declared_body(
    keepalive_http_server: KeepAliveServer,
) -> None:
    content = FailsWhenReadPastExactLengthFile(b"known-length-body")
    url = keepalive_http_server.url + KEEPALIVE_PATH

    async with foghttp.AsyncClient() as client:
        first_response = await client.post(url, content=content)
        second_response = await client.get(url)
        stats = client.stats()

    assert first_response.status_code == OK
    assert second_response.status_code == OK
    assert_reused_connection_stats(stats, KNOWN_LENGTH_REQUEST_COUNT)
    assert_single_connection_snapshot(keepalive_http_server.snapshot(), KNOWN_LENGTH_REQUEST_COUNT)
    assert content.read_past_declared_body is False
    assert content.close_calls == 1


async def test_async_zero_length_file_upload_reuses_connection(
    keepalive_http_server: KeepAliveServer,
) -> None:
    url = keepalive_http_server.url + KEEPALIVE_PATH

    async with foghttp.AsyncClient() as client:
        first_response = await client.post(url, content=BytesIO())
        second_response = await client.get(url)
        stats = client.stats()

    assert first_response.status_code == OK
    assert second_response.status_code == OK
    assert_reused_connection_stats(stats, KNOWN_LENGTH_REQUEST_COUNT)
    assert_single_connection_snapshot(keepalive_http_server.snapshot(), KNOWN_LENGTH_REQUEST_COUNT)


async def test_async_delayed_zero_length_file_upload_reuses_connection(
    keepalive_http_server: KeepAliveServer,
) -> None:
    url = keepalive_http_server.url + KEEPALIVE_PATH

    async with foghttp.AsyncClient() as client:
        first_response = await client.post(url, content=DelayedCloseEmptyFile())
        second_response = await client.get(url)
        stats = client.stats()

    assert first_response.status_code == OK
    assert second_response.status_code == OK
    assert_reused_connection_stats(stats, KNOWN_LENGTH_REQUEST_COUNT)
    assert_single_connection_snapshot(keepalive_http_server.snapshot(), KNOWN_LENGTH_REQUEST_COUNT)


@pytest.mark.parametrize(
    ("content", "declared_length", "request_succeeds"),
    MISREPORTED_LENGTH_CASES,
)
async def test_async_invalid_known_length_upload_aborts_connection_before_recovery(
    keepalive_http_server: KeepAliveServer,
    content: bytes,
    declared_length: int,
    *,
    request_succeeds: bool,
) -> None:
    source = MisreportedLengthFile(content, declared_length)
    url = keepalive_http_server.url + KEEPALIVE_PATH

    async with foghttp.AsyncClient() as client:
        if request_succeeds:
            assert (await client.post(url, content=source)).status_code == OK
        else:
            with pytest.raises(foghttp.RequestError, match="early end"):
                await client.post(url, content=source)
        recovery_response = await client.get(url)
        stats = client.stats()

    snapshot = keepalive_http_server.snapshot()
    assert recovery_response.status_code == OK
    assert stats.connections_opened == EXPECTED_DISTINCT_CONNECTIONS
    assert stats.connections_reused == 0
    assert stats.connections_closed == 1
    assert stats.connections_aborted == 1
    assert stats.connections_open_failed == 0
    assert stats.idle_connections == 1
    assert snapshot.connection_count == EXPECTED_DISTINCT_CONNECTIONS
    assert source.close_calls == 1


async def _chunked_body() -> AsyncIterator[bytes]:
    yield CHUNKED_BODY


@pytest.mark.parametrize("status_code", METHOD_PRESERVING_REDIRECTS)
async def test_async_method_preserving_redirect_reuses_connection(
    keepalive_http_server: KeepAliveServer,
    status_code: int,
) -> None:
    limits = foghttp.Limits(keepalive=True, max_idle_connections_per_host=1)
    url = f"{keepalive_http_server.url}{REDIRECT_PATH_PREFIX}{status_code}"

    async with foghttp.AsyncClient(follow_redirects=True, limits=limits) as client:
        response = await client.post(url, content=REDIRECT_REQUEST_BODY)
        stats = client.stats()

    assert response.status_code == OK
    assert response.request.method == "POST"
    assert len(response.history) == 1
    assert response.history[0].status_code == status_code
    assert_redirect_preserved_request(response, REDIRECT_REQUEST_BODY)
    assert_reused_connection_stats(stats, REDIRECT_REQUEST_COUNT)
    assert_single_connection_snapshot(keepalive_http_server.snapshot(), REDIRECT_REQUEST_COUNT)


@pytest.mark.parametrize("status_code", METHOD_PRESERVING_REDIRECTS)
async def test_async_streaming_factory_redirect_reuses_connection(
    keepalive_http_server: KeepAliveServer,
    status_code: int,
) -> None:
    content = TrackedFactory(partial(AsyncChunks, (REDIRECT_REQUEST_BODY,)))
    url = f"{keepalive_http_server.url}{REDIRECT_PATH_PREFIX}{status_code}"

    async with foghttp.AsyncClient(follow_redirects=True) as client:
        response = await client.post(url, content=content)
        stats = client.stats()

    assert response.status_code == OK
    assert_redirect_preserved_request(response, REDIRECT_REQUEST_BODY)
    assert content.calls == REDIRECT_REQUEST_COUNT
    assert content.close_calls == 0
    assert_reused_connection_stats(stats, REDIRECT_REQUEST_COUNT)
    assert_single_connection_snapshot(keepalive_http_server.snapshot(), REDIRECT_REQUEST_COUNT)


async def test_async_transport_state_reports_idle_connection_detail(
    keepalive_http_server: KeepAliveServer,
) -> None:
    limits = foghttp.Limits(keepalive=True, max_idle_connections_per_host=1)

    async with foghttp.AsyncClient(limits=limits) as client:
        response = await client.get(keepalive_http_server.url + KEEPALIVE_PATH)
        state = await wait_for_async_transport_state(
            client,
            lambda state: has_idle_origin_detail(state, keepalive_http_server.url),
            message="expected per-origin idle connection detail",
        )

    origin_state = state["origins"][keepalive_http_server.url]

    assert response.status_code == OK
    assert set(state["origins"]) == {keepalive_http_server.url}
    assert origin_state["active_requests"] == 0
    assert origin_state["pending_requests"] == 0
    assert origin_state["connections_reused"] == 0
    assert origin_state["connections_closed"] == 0


async def test_async_idle_timeout_eviction_is_reported(
    keepalive_http_server: KeepAliveServer,
) -> None:
    limits = foghttp.Limits(
        keepalive=True,
        max_idle_connections_per_host=1,
        idle_timeout=IDLE_TIMEOUT_SECONDS,
    )

    async with foghttp.AsyncClient(limits=limits) as client:
        response = await client.get(keepalive_http_server.url + KEEPALIVE_PATH)
        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.idle_connections == 1,
            message="expected reusable connection to enter the idle pool",
        )
        await wait_for_async_transport_stats(
            client,
            is_idle_timeout_eviction_reported,
            message="expected idle timeout eviction to be visible in stats",
        )
        stats = client.stats()
        state = client.dump_transport_state()

    origin_state = state["origins"][keepalive_http_server.url]

    assert response.status_code == OK
    assert stats.connections_closed == 1
    assert stats.idle_timeout_evictions == 1
    assert origin_state["connections_closed"] == 1
    assert origin_state["idle_timeout_evictions"] == 1


async def test_async_early_remote_idle_close_is_not_idle_timeout_eviction(
    early_close_keepalive_http_server: KeepAliveServer,
) -> None:
    limits = foghttp.Limits(
        keepalive=True,
        max_idle_connections_per_host=1,
        idle_timeout=LONG_IDLE_TIMEOUT_SECONDS,
    )
    url = early_close_keepalive_http_server.url + KEEPALIVE_PATH

    async with foghttp.AsyncClient(limits=limits) as client:
        first_response = await client.post(url, content=b"first-body")
        second_response = await client.post(url, content=b"second-body")
        await wait_for_async_transport_stats(
            client,
            is_early_remote_idle_close_observed,
            message="expected early remote close to force a new connection",
        )
        stats = client.stats()
        state = client.dump_transport_state()

    origin_state = state["origins"][early_close_keepalive_http_server.url]

    assert first_response.status_code == OK
    assert second_response.status_code == OK
    assert_distinct_connection_payloads(first_response.json(), second_response.json())
    assert_distinct_connection_snapshot(early_close_keepalive_http_server.snapshot())
    assert stats.connections_opened == EXPECTED_DISTINCT_CONNECTIONS
    assert stats.connections_closed >= 1
    assert stats.connections_reused == 0
    assert stats.idle_timeout_evictions == 0
    assert origin_state["connections_opened"] == EXPECTED_DISTINCT_CONNECTIONS
    assert origin_state["connections_closed"] >= 1
    assert origin_state["connections_reused"] == 0
    assert origin_state["idle_timeout_evictions"] == 0
