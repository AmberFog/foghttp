import asyncio
from functools import partial
from typing import TYPE_CHECKING

import pytest

import foghttp
from foghttp._client import asyncio_futures
import foghttp._foghttp as _foghttp  # noqa: PLR0402
from tests.client_telemetry.assertions import assert_stream_completion
from tests.client_telemetry.models import FailOnEventTelemetrySink

from .constants import WAIT_TIMEOUT
from .payloads import EncodedResponse
from .server import ServerFactory


if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.mark.parametrize("action", ["close", "cancel", "client-close"])
@pytest.mark.parametrize("encoding", ["gzip", "identity"])
async def test_known_native_error_survives_close_before_python_delivery(
    decompression_server: ServerFactory,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    encoding: str,
) -> None:
    recorded = asyncio.Event()
    pending: list[Callable[[], None]] = []
    deliver = asyncio_futures.set_exception_if_pending

    def hold_error(future: asyncio.Future[object], error: BaseException) -> None:
        pending.append(partial(deliver, future, error))
        recorded.set()

    monkeypatch.setattr(asyncio_futures, "set_exception_if_pending", hold_error)
    server = decompression_server(EncodedResponse(b"invalid", encodings=(encoding,)))
    sink = FailOnEventTelemetrySink(foghttp.TelemetryEventType.RESPONSE_BODY_FINISHED)
    expected = foghttp.ResponseDecodingError if encoding == "gzip" else foghttp.ResponseBodyTooLargeError
    async with (
        foghttp.AsyncClient(
            trust_env=False,
            limits=foghttp.Limits(max_stream_decoded_bytes=0),
            telemetry=foghttp.TelemetryConfig(sink=sink),
        ) as client,
        client.stream("GET", server.url, decode_content=True) as response,
    ):
        read = asyncio.create_task(anext(response.aiter_bytes()))
        try:
            await asyncio.wait_for(recorded.wait(), WAIT_TIMEOUT)
            assert client.stats().failed_requests == 1
            assert client.stats().stream_decoder_reserved_bytes == 0
            assert client.stats().active_requests == 0
            if action == "cancel":
                read.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await read
            else:
                if action == "client-close":
                    await client.aclose()
                response.close()
                for deliver_error in pending:
                    deliver_error()
            if action != "cancel":
                with pytest.raises(expected):
                    await read
            response.close()
        finally:
            if not read.done():
                read.cancel()
            await asyncio.gather(read, return_exceptions=True)
    assert_stream_completion(sink.events, outcome=foghttp.TelemetryRequestOutcome.ERROR, error_type=expected.__name__)


@pytest.mark.parametrize("encoding", ["gzip", "identity"])
def test_sync_close_preserves_failure_already_known_to_native_reader(
    decompression_server: ServerFactory,
    encoding: str,
) -> None:
    server = decompression_server(EncodedResponse(b"invalid", encodings=(encoding,)))
    sink = FailOnEventTelemetrySink(foghttp.TelemetryEventType.RESPONSE_BODY_FINISHED)
    expected = "ResponseDecodingError" if encoding == "gzip" else "ResponseBodyTooLargeError"
    raw_expected = (
        _foghttp.FogHttpResponseDecodingError if encoding == "gzip" else _foghttp.FogHttpResponseBodyTooLargeError
    )
    with (
        foghttp.Client(
            trust_env=False,
            limits=foghttp.Limits(max_stream_decoded_bytes=0),
            telemetry=foghttp.TelemetryConfig(sink=sink),
        ) as client,
        client.stream("GET", server.url, decode_content=True) as response,
    ):
        with pytest.raises(raw_expected):
            response._raw.next_chunk()  # noqa: SLF001 - close between native failure and public delivery
        response.close()
        response.close()
        assert client.stats().active_requests == 0
        assert client.stats().failed_requests == 1
        assert client.stats().stream_decoder_reserved_bytes == 0
    assert_stream_completion(sink.events, outcome=foghttp.TelemetryRequestOutcome.ERROR, error_type=expected)
