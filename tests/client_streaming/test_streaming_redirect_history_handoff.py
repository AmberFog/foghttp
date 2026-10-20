import pytest

import foghttp
from tests.client_telemetry.models import RecordingTelemetrySink
from tests.support.transport_stats import wait_for_async_transport_stats, wait_for_sync_transport_stats

from .stream_readers import collect_stream_chunks
from .streaming_history_assertions import assert_public_stream_history, stream_resources_released
from .streaming_history_conversion import HISTORY_CONVERSION_ERROR, observe_history_conversion
from .streaming_history_sources import FINAL_BODY, FINAL_WIRE_BODY, RECOVERY_BODY, StreamingHistoryServer


@pytest.mark.parametrize("decode_content", [False, True], ids=["raw", "decoded"])
def test_sync_stream_hands_off_history_without_retaining_native_payload(
    streaming_history_server: StreamingHistoryServer,
    *,
    decode_content: bool,
) -> None:
    expected_body = FINAL_BODY if decode_content else FINAL_WIRE_BODY
    with foghttp.Client(
        follow_redirects=True,
        retry=foghttp.RetryPolicy(retries=1, backoff=0, jitter=0),
        trust_env=False,
    ) as client:
        with client.stream(
            "GET",
            streaming_history_server.start_url,
            headers={"x-history-request": "preserved"},
            extensions={"history-marker": "bound"},
            decode_content=decode_content,
        ) as response:
            assert_public_stream_history(response, streaming_history_server)
            assert client.stats().buffered_response_bytes == 0
            assert ("content-encoding" not in response.headers) == decode_content
            assert response._raw.history == []  # noqa: SLF001 - Native ownership is the regression boundary.
            assert b"".join(response.iter_bytes()) == expected_body
            assert_public_stream_history(response, streaming_history_server)
            assert response._raw.history == []  # noqa: SLF001 - Native ownership is the regression boundary.
        response.close()
        assert_public_stream_history(response, streaming_history_server)
        assert response._raw.history == []  # noqa: SLF001 - Native ownership is the regression boundary.
        wait_for_sync_transport_stats(
            client,
            stream_resources_released,
            message="stream history handoff and EOF must release all reservations and request slots",
        )
        assert client.get(f"{streaming_history_server.url}/healthy").content == RECOVERY_BODY
        assert client.stats().connections_opened == 1
        assert client.stats().connections_reused == len(streaming_history_server.history_bodies) + 1


@pytest.mark.parametrize("decode_content", [False, True], ids=["raw", "decoded"])
async def test_async_stream_hands_off_history_without_retaining_native_payload(
    streaming_history_server: StreamingHistoryServer,
    *,
    decode_content: bool,
) -> None:
    expected_body = FINAL_BODY if decode_content else FINAL_WIRE_BODY
    async with foghttp.AsyncClient(
        follow_redirects=True,
        retry=foghttp.RetryPolicy(retries=1, backoff=0, jitter=0),
        trust_env=False,
    ) as client:
        async with client.stream(
            "GET",
            streaming_history_server.start_url,
            headers={"x-history-request": "preserved"},
            extensions={"history-marker": "bound"},
            decode_content=decode_content,
        ) as response:
            assert_public_stream_history(response, streaming_history_server)
            assert client.stats().buffered_response_bytes == 0
            assert ("content-encoding" not in response.headers) == decode_content
            assert response._raw.history == []  # noqa: SLF001 - Native ownership is the regression boundary.
            assert b"".join(await collect_stream_chunks(response.aiter_bytes())) == expected_body
            assert_public_stream_history(response, streaming_history_server)
            assert response._raw.history == []  # noqa: SLF001 - Native ownership is the regression boundary.
        await response.aclose()
        assert_public_stream_history(response, streaming_history_server)
        assert response._raw.history == []  # noqa: SLF001 - Native ownership is the regression boundary.
        await wait_for_async_transport_stats(
            client,
            stream_resources_released,
            message="stream history handoff and EOF must release all reservations and request slots",
        )
        assert (await client.get(f"{streaming_history_server.url}/healthy")).content == RECOVERY_BODY
        assert client.stats().connections_opened == 1
        assert client.stats().connections_reused == len(streaming_history_server.history_bodies) + 1


@pytest.mark.parametrize("decode_content", [False, True], ids=["raw", "decoded"])
@pytest.mark.parametrize("failure_index", [0, 1], ids=["first-history", "middle-history"])
def test_sync_history_conversion_failure_reclaims_resources_with_live_traceback(
    conversion_history_server: StreamingHistoryServer,
    monkeypatch: pytest.MonkeyPatch,
    failure_index: int,
    *,
    decode_content: bool,
) -> None:
    limits = foghttp.Limits(max_active_requests=1, max_pending_requests=0)
    with foghttp.Client(follow_redirects=True, limits=limits, trust_env=False) as client:
        with monkeypatch.context() as patch:
            probe = observe_history_conversion(patch, client, failure_index=failure_index)
            with (
                pytest.raises(RuntimeError, match=HISTORY_CONVERSION_ERROR) as caught,
                client.stream("GET", conversion_history_server.start_url, decode_content=decode_content),
            ):
                pytest.fail("failed conversion must not yield a public stream")
        assert caught.value.__traceback__ is not None
        assert len(probe.history_items) == failure_index + 1
        assert probe.reserved_before[0] == sum(map(len, conversion_history_server.history_bodies))
        wait_for_sync_transport_stats(
            client,
            stream_resources_released,
            message="failed conversion must release resources while the exception and traceback remain alive",
        )
        assert client.stats().active_connections == 0
        assert client.stats().response_body_aborted == client.stats().connections_aborted == 1
        assert client.get(f"{conversion_history_server.url}/healthy").content == RECOVERY_BODY
        assert caught.value.__traceback__ is not None
        assert probe.raw_stream is not None
        probe.raw_stream.close()
        probe.raw_stream.close()
        for item in probe.history_items:
            item.release_buffered_body_reservations()
            item.release_buffered_body_reservations()
        assert stream_resources_released(client.stats())


@pytest.mark.parametrize("decode_content", [False, True], ids=["raw", "decoded"])
@pytest.mark.parametrize("failure_index", [0, 1], ids=["first-history", "middle-history"])
async def test_async_history_conversion_failure_reclaims_resources_with_live_traceback(
    conversion_history_server: StreamingHistoryServer,
    monkeypatch: pytest.MonkeyPatch,
    failure_index: int,
    *,
    decode_content: bool,
) -> None:
    limits = foghttp.Limits(max_active_requests=1, max_pending_requests=0)
    async with foghttp.AsyncClient(follow_redirects=True, limits=limits, trust_env=False) as client:
        with monkeypatch.context() as patch:
            probe = observe_history_conversion(patch, client, failure_index=failure_index)
            with pytest.raises(RuntimeError, match=HISTORY_CONVERSION_ERROR) as caught:
                async with client.stream("GET", conversion_history_server.start_url, decode_content=decode_content):
                    pytest.fail("failed conversion must not yield a public stream")
        assert caught.value.__traceback__ is not None
        assert len(probe.history_items) == failure_index + 1
        assert probe.reserved_before[0] == sum(map(len, conversion_history_server.history_bodies))
        await wait_for_async_transport_stats(
            client,
            stream_resources_released,
            message="failed conversion must release resources while the exception and traceback remain alive",
        )
        assert client.stats().active_connections == 0
        assert client.stats().response_body_aborted == client.stats().connections_aborted == 1
        assert (await client.get(f"{conversion_history_server.url}/healthy")).content == RECOVERY_BODY
        assert caught.value.__traceback__ is not None
        assert probe.raw_stream is not None
        probe.raw_stream.close()
        probe.raw_stream.close()
        for item in probe.history_items:
            item.release_buffered_body_reservations()
            item.release_buffered_body_reservations()
        assert stream_resources_released(client.stats())


@pytest.mark.parametrize("decode_content", [False, True], ids=["raw", "decoded"])
def test_sync_history_reservations_cover_each_public_bytes_conversion(
    conversion_history_server: StreamingHistoryServer,
    monkeypatch: pytest.MonkeyPatch,
    *,
    decode_content: bool,
) -> None:
    expected_body = FINAL_BODY if decode_content else FINAL_WIRE_BODY
    with foghttp.Client(follow_redirects=True, trust_env=False) as client:
        probe = observe_history_conversion(monkeypatch, client)
        with client.stream("GET", conversion_history_server.start_url, decode_content=decode_content) as response:
            for hop, reserved in enumerate(probe.reserved_before):
                assert reserved >= sum(map(len, conversion_history_server.history_bodies[hop:]))
            assert len(probe.reserved_before) == len(conversion_history_server.history_bodies)
            assert client.stats().buffered_response_bytes == 0
            assert client.stats().active_requests == 1
            assert (client.stats().stream_decoder_reserved_bytes > 0) == decode_content
            assert b"".join(response.iter_bytes()) == expected_body
        assert stream_resources_released(client.stats())


@pytest.mark.parametrize("decode_content", [False, True], ids=["raw", "decoded"])
async def test_async_history_reservations_cover_each_public_bytes_conversion(
    conversion_history_server: StreamingHistoryServer,
    monkeypatch: pytest.MonkeyPatch,
    *,
    decode_content: bool,
) -> None:
    expected_body = FINAL_BODY if decode_content else FINAL_WIRE_BODY
    async with foghttp.AsyncClient(follow_redirects=True, trust_env=False) as client:
        probe = observe_history_conversion(monkeypatch, client)
        async with client.stream("GET", conversion_history_server.start_url, decode_content=decode_content) as response:
            for hop, reserved in enumerate(probe.reserved_before):
                assert reserved >= sum(map(len, conversion_history_server.history_bodies[hop:]))
            assert len(probe.reserved_before) == len(conversion_history_server.history_bodies)
            assert client.stats().buffered_response_bytes == 0
            assert client.stats().active_requests == 1
            assert (client.stats().stream_decoder_reserved_bytes > 0) == decode_content
            assert b"".join(await collect_stream_chunks(response.aiter_bytes())) == expected_body
        assert stream_resources_released(client.stats())


@pytest.mark.parametrize("decode_content", [False, True], ids=["raw", "decoded"])
def test_sync_early_close_preserves_native_redirect_hop_after_handoff(
    conversion_history_server: StreamingHistoryServer,
    *,
    decode_content: bool,
) -> None:
    sink = RecordingTelemetrySink()
    with foghttp.Client(
        follow_redirects=True,
        telemetry=foghttp.TelemetryConfig(sink=sink),
        trust_env=False,
    ) as client:
        with client.stream("GET", conversion_history_server.start_url, decode_content=decode_content) as response:
            assert response._raw.history == []  # noqa: SLF001 - Native ownership is the regression boundary.
        response.close()
        aborted = [event for event in sink.events if event.event_type is foghttp.TelemetryEventType.CONNECTION_ABORTED]
        assert len(aborted) == 1
        assert aborted[0].redirect_hop == len(conversion_history_server.history_bodies)
        assert client.stats().response_body_aborted == client.stats().connections_aborted == 1
        assert stream_resources_released(client.stats())
        assert client.get(f"{conversion_history_server.url}/healthy").content == RECOVERY_BODY


@pytest.mark.parametrize("decode_content", [False, True], ids=["raw", "decoded"])
async def test_async_early_close_preserves_native_redirect_hop_after_handoff(
    conversion_history_server: StreamingHistoryServer,
    *,
    decode_content: bool,
) -> None:
    sink = RecordingTelemetrySink()
    async with foghttp.AsyncClient(
        follow_redirects=True,
        telemetry=foghttp.TelemetryConfig(sink=sink),
        trust_env=False,
    ) as client:
        async with client.stream("GET", conversion_history_server.start_url, decode_content=decode_content) as response:
            assert response._raw.history == []  # noqa: SLF001 - Native ownership is the regression boundary.
        await response.aclose()
        aborted = [event for event in sink.events if event.event_type is foghttp.TelemetryEventType.CONNECTION_ABORTED]
        assert len(aborted) == 1
        assert aborted[0].redirect_hop == len(conversion_history_server.history_bodies)
        assert client.stats().response_body_aborted == client.stats().connections_aborted == 1
        assert stream_resources_released(client.stats())
        assert (await client.get(f"{conversion_history_server.url}/healthy")).content == RECOVERY_BODY
