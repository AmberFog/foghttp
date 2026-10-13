import asyncio
from contextlib import suppress
from dataclasses import replace

import pytest

import foghttp
from tests.support.transport_stats import wait_for_async_transport_stats

from .cases import GATED_BODIES
from .constants import FIRST_OUTPUT, GZIP_RESERVATION, LARGE_BODY, WAIT_TIMEOUT
from .payloads import EncodedResponse, gated_gzip, gzip_bytes
from .read_actions import read_after_signal, read_async_prefix, read_async_until_transport_eof
from .server import ServerFactory


@pytest.mark.parametrize(("case", "prefix", "tail", "reservation"), GATED_BODIES)
async def test_async_delivers_prefix_before_network_tail_and_reuses_connection(
    decompression_server: ServerFactory,
    case: EncodedResponse,
    prefix: bytes,
    tail: bytes,
    reservation: int,
) -> None:
    server = decompression_server(case)
    async with foghttp.AsyncClient(trust_env=False) as client:
        async with client.stream("GET", server.url, decode_content=True) as response:
            iterator = response.aiter_bytes()
            assert await asyncio.wait_for(read_async_prefix(iterator, len(prefix)), WAIT_TIMEOUT) == prefix
            assert not server.release_tail.is_set()
            assert client.stats().stream_decoder_reserved_bytes == reservation
            server.release_tail.set()
            assert b"".join([chunk async for chunk in iterator]) == tail
            connection_id = response.headers["x-connection-id"]
        recovery = await client.get(f"{server.url}/healthy")
        assert recovery.headers["x-connection-id"] == connection_id
        assert client.stats().stream_decoder_reserved_bytes == 0


@pytest.mark.parametrize("close_client", [False, True], ids=["response-close", "client-close"])
async def test_async_partial_close_aborts_unread_transport(
    decompression_server: ServerFactory,
    *,
    close_client: bool,
) -> None:
    server = decompression_server(gated_gzip())
    async with foghttp.AsyncClient(trust_env=False) as client:
        raw_client = client._raw_client()  # noqa: SLF001 - public stats reject a closed client
        async with client.stream("GET", server.url, decode_content=True) as response:
            iterator = response.aiter_bytes()
            assert await asyncio.wait_for(read_async_prefix(iterator, len(FIRST_OUTPUT)), WAIT_TIMEOUT) == FIRST_OUTPUT
            connection_id = response.headers["x-connection-id"]
            if close_client:
                await client.aclose()
                assert raw_client.stats().stream_decoder_reserved_bytes == 0
                assert raw_client.stats().active_requests == 0
            await response.aclose()
            await response.aclose()
        await wait_for_async_transport_stats(
            raw_client,
            lambda stats: stats.active_requests == 0 and stats.stream_decoder_reserved_bytes == 0,
            message="partial close must release decoder resources",
        )
        assert raw_client.stats().response_body_aborted == 1
        if not close_client:
            recovery = await client.get(f"{server.url}/healthy")
            assert recovery.headers["x-connection-id"] != connection_id


async def test_async_cancel_pending_decoded_read_releases_resources(decompression_server: ServerFactory) -> None:
    server = decompression_server(gated_gzip())
    async with foghttp.AsyncClient(trust_env=False, lifecycle_debug=foghttp.AsyncLifecycleDebugConfig()) as client:
        async with client.stream("GET", server.url, decode_content=True) as response:
            iterator = response.aiter_bytes()
            assert await asyncio.wait_for(read_async_prefix(iterator, len(FIRST_OUTPUT)), WAIT_TIMEOUT) == FIRST_OUTPUT
            started = asyncio.Event()
            task = asyncio.create_task(read_after_signal(iterator, started))
            try:
                await asyncio.wait_for(started.wait(), WAIT_TIMEOUT)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            await wait_for_async_transport_stats(
                client,
                lambda stats: stats.active_requests == 0 and stats.stream_decoder_reserved_bytes == 0,
                message="cancelled decoded read retained its reservation",
            )
            client.assert_no_lifecycle_leaks()
        assert client.stats().response_body_aborted == 1
        assert (await client.get(f"{server.url}/healthy")).content == b"healthy"


@pytest.mark.parametrize("close_client", [False, True], ids=["exhaust", "client-close"])
async def test_async_transport_eof_retains_decoder_until_content_terminal(
    decompression_server: ServerFactory,
    *,
    close_client: bool,
) -> None:
    server = decompression_server(EncodedResponse(gzip_bytes(LARGE_BODY)))
    async with foghttp.AsyncClient(trust_env=False) as client:
        raw_client = client._raw_client()  # noqa: SLF001 - inspect cleanup after public close
        async with client.stream("GET", server.url, decode_content=True) as response:
            iterator = response.aiter_bytes()
            prefix = await read_async_until_transport_eof(client, iterator)
            assert LARGE_BODY.startswith(prefix)
            assert len(prefix) < len(LARGE_BODY)
            assert client.stats().active_requests == 1
            assert client.stats().stream_decoder_reserved_bytes == GZIP_RESERVATION
            if close_client:
                await client.aclose()
                assert raw_client.stats().stream_decoder_reserved_bytes == 0
                assert raw_client.stats().active_requests == 0
            else:
                recovery = await client.get(f"{server.url}/healthy")
                assert recovery.headers["x-connection-id"] == response.headers["x-connection-id"]
                assert prefix + b"".join([chunk async for chunk in iterator]) == LARGE_BODY
            await response.aclose()
        assert raw_client.stats().active_requests == 0
        assert raw_client.stats().stream_decoder_reserved_bytes == 0
        assert raw_client.stats().response_body_aborted == 0


async def test_async_late_checksum_error_does_not_abort_reassigned_connection(
    decompression_server: ServerFactory,
) -> None:
    encoded = bytearray(gzip_bytes(LARGE_BODY))
    encoded[-8] ^= 1
    server = decompression_server(EncodedResponse(bytes(encoded)))
    async with foghttp.AsyncClient(trust_env=False) as client:
        async with client.stream("GET", server.url, decode_content=True) as response:
            iterator = response.aiter_bytes()
            prefix = await read_async_until_transport_eof(client, iterator)
            assert LARGE_BODY.startswith(prefix)
            async with client.stream("GET", f"{server.url}/healthy") as borrowed:
                assert borrowed.headers["x-connection-id"] == response.headers["x-connection-id"]
                with pytest.raises(foghttp.ResponseDecodingError):
                    _ = [chunk async for chunk in iterator]
                assert b"".join([chunk async for chunk in borrowed.aiter_bytes()]) == b"healthy"
            recovery = await client.get(f"{server.url}/healthy")
            assert recovery.headers["x-connection-id"] == response.headers["x-connection-id"]
        assert client.stats().failed_requests == 1
        assert client.stats().response_body_aborted == 0
        assert client.stats().stream_decoder_reserved_bytes == 0


@pytest.mark.parametrize(
    ("close_before_tail", "error_type"),
    [(False, foghttp.ReadTimeout), (True, foghttp.RequestError)],
)
async def test_async_decoded_transport_failure_preserves_error_and_releases_resources(
    decompression_server: ServerFactory,
    error_type: type[foghttp.RequestError],
    *,
    close_before_tail: bool,
) -> None:
    server = decompression_server(replace(gated_gzip(), close_before_tail=close_before_tail))
    async with foghttp.AsyncClient(trust_env=False) as client:
        async with client.stream(
            "GET",
            server.url,
            decode_content=True,
            timeout=foghttp.Timeouts(read=1.0),
        ) as response:
            iterator = response.aiter_bytes()
            assert await asyncio.wait_for(read_async_prefix(iterator, len(FIRST_OUTPUT)), WAIT_TIMEOUT) == FIRST_OUTPUT
            if close_before_tail:
                server.release_tail.set()
            with pytest.raises(error_type) as error:
                _ = [chunk async for chunk in iterator]
            assert type(error.value) is error_type
            if isinstance(error.value, foghttp.ReadTimeout):
                assert error.value.phase == "response_body"
        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.stream_decoder_reserved_bytes == 0,
            message="decoded transport failure retained resources",
        )
        assert client.stats().response_body_aborted == 1
        assert client.stats().failed_requests == 1
        recovery = await client.get(f"{server.url}/healthy")
        assert recovery.content == b"healthy"
        assert recovery.headers["x-connection-id"] != response.headers["x-connection-id"]
