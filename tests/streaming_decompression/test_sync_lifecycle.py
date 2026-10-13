from dataclasses import replace

import pytest

import foghttp
from tests.support.transport_stats import wait_for_sync_transport_stats

from .cases import GATED_BODIES
from .constants import FIRST_OUTPUT, GZIP_RESERVATION, LARGE_BODY, WAIT_TIMEOUT
from .payloads import EncodedResponse, gated_gzip, gzip_bytes
from .read_actions import read_sync_prefix, read_sync_until_transport_eof
from .server import ServerFactory


@pytest.mark.parametrize(("case", "prefix", "tail", "reservation"), GATED_BODIES)
def test_sync_delivers_prefix_before_network_tail_and_reuses_connection(
    decompression_server: ServerFactory,
    case: EncodedResponse,
    prefix: bytes,
    tail: bytes,
    reservation: int,
) -> None:
    server = decompression_server(case)
    with foghttp.Client(trust_env=False) as client:
        with client.stream("GET", server.url, decode_content=True) as response:
            iterator = response.iter_bytes()
            assert read_sync_prefix(iterator, len(prefix)) == prefix
            assert server.prefix_sent.wait(timeout=WAIT_TIMEOUT)
            assert not server.release_tail.is_set()
            assert client.stats().stream_decoder_reserved_bytes == reservation
            server.release_tail.set()
            assert b"".join(iterator) == tail
            connection_id = response.headers["x-connection-id"]
        recovery = client.get(f"{server.url}/healthy")
        assert recovery.headers["x-connection-id"] == connection_id
        assert client.stats().stream_decoder_reserved_bytes == 0


@pytest.mark.parametrize("close_client", [False, True], ids=["response-close", "client-close"])
def test_sync_partial_close_aborts_unread_transport(
    decompression_server: ServerFactory,
    *,
    close_client: bool,
) -> None:
    server = decompression_server(gated_gzip())
    with foghttp.Client(trust_env=False) as client:
        raw_client = client._raw_client()  # noqa: SLF001 - public stats reject a closed client
        with client.stream("GET", server.url, decode_content=True) as response:
            iterator = response.iter_bytes()
            assert read_sync_prefix(iterator, len(FIRST_OUTPUT)) == FIRST_OUTPUT
            connection_id = response.headers["x-connection-id"]
            if close_client:
                client.close()
                assert raw_client.stats().stream_decoder_reserved_bytes == 0
                assert raw_client.stats().active_requests == 0
            response.close()
            response.close()
        wait_for_sync_transport_stats(
            raw_client,
            lambda stats: stats.active_requests == 0 and stats.stream_decoder_reserved_bytes == 0,
            message="partial close must release decoder resources",
        )
        assert raw_client.stats().response_body_aborted == 1
        if not close_client:
            recovery = client.get(f"{server.url}/healthy")
            assert recovery.headers["x-connection-id"] != connection_id


@pytest.mark.parametrize("close_client", [False, True], ids=["exhaust", "client-close"])
def test_sync_transport_eof_retains_decoder_until_content_terminal(
    decompression_server: ServerFactory,
    *,
    close_client: bool,
) -> None:
    server = decompression_server(EncodedResponse(gzip_bytes(LARGE_BODY)))
    with foghttp.Client(trust_env=False) as client:
        raw_client = client._raw_client()  # noqa: SLF001 - inspect cleanup after public close
        with client.stream("GET", server.url, decode_content=True) as response:
            iterator = response.iter_bytes()
            prefix = read_sync_until_transport_eof(client, iterator)
            assert LARGE_BODY.startswith(prefix)
            assert len(prefix) < len(LARGE_BODY)
            assert client.stats().active_requests == 1
            assert client.stats().stream_decoder_reserved_bytes == GZIP_RESERVATION
            if close_client:
                client.close()
                assert raw_client.stats().stream_decoder_reserved_bytes == 0
                assert raw_client.stats().active_requests == 0
            else:
                recovery = client.get(f"{server.url}/healthy")
                assert recovery.headers["x-connection-id"] == response.headers["x-connection-id"]
                assert prefix + b"".join(iterator) == LARGE_BODY
            response.close()
        assert raw_client.stats().active_requests == 0
        assert raw_client.stats().stream_decoder_reserved_bytes == 0
        assert raw_client.stats().response_body_aborted == 0


def test_sync_late_checksum_error_does_not_abort_reassigned_connection(decompression_server: ServerFactory) -> None:
    encoded = bytearray(gzip_bytes(LARGE_BODY))
    encoded[-8] ^= 1
    server = decompression_server(EncodedResponse(bytes(encoded)))
    with foghttp.Client(trust_env=False) as client:
        with client.stream("GET", server.url, decode_content=True) as response:
            iterator = response.iter_bytes()
            prefix = read_sync_until_transport_eof(client, iterator)
            assert LARGE_BODY.startswith(prefix)
            with client.stream("GET", f"{server.url}/healthy") as borrowed:
                assert borrowed.headers["x-connection-id"] == response.headers["x-connection-id"]
                with pytest.raises(foghttp.ResponseDecodingError):
                    list(iterator)
                assert b"".join(borrowed.iter_bytes()) == b"healthy"
            recovery = client.get(f"{server.url}/healthy")
            assert recovery.headers["x-connection-id"] == response.headers["x-connection-id"]
        assert client.stats().failed_requests == 1
        assert client.stats().response_body_aborted == 0
        assert client.stats().stream_decoder_reserved_bytes == 0


@pytest.mark.parametrize(
    ("close_before_tail", "error_type"),
    [(False, foghttp.ReadTimeout), (True, foghttp.RequestError)],
)
def test_sync_decoded_transport_failure_preserves_error_and_releases_resources(
    decompression_server: ServerFactory,
    error_type: type[foghttp.RequestError],
    *,
    close_before_tail: bool,
) -> None:
    server = decompression_server(replace(gated_gzip(), close_before_tail=close_before_tail))
    with foghttp.Client(trust_env=False) as client:
        with client.stream("GET", server.url, decode_content=True, timeout=foghttp.Timeouts(read=1.0)) as response:
            iterator = response.iter_bytes()
            assert read_sync_prefix(iterator, len(FIRST_OUTPUT)) == FIRST_OUTPUT
            if close_before_tail:
                server.release_tail.set()
            with pytest.raises(error_type) as error:
                list(iterator)
            assert type(error.value) is error_type
            if isinstance(error.value, foghttp.ReadTimeout):
                assert error.value.phase == "response_body"
        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.stream_decoder_reserved_bytes == 0,
            message="decoded transport failure retained resources",
        )
        assert client.stats().response_body_aborted == 1
        assert client.stats().failed_requests == 1
        recovery = client.get(f"{server.url}/healthy")
        assert recovery.content == b"healthy"
        assert recovery.headers["x-connection-id"] != response.headers["x-connection-id"]
