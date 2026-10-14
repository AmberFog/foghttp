from http import HTTPStatus

import pytest

import foghttp
from foghttp.auth import AuthRequest
from tests.client_proxy.http_proxy_server import PROXY_REDIRECT_PATH, SyncHTTPProxy
from tests.client_retry.constants import CLOSE_THEN_OK_PATH, STATUS_THEN_OK_PATH
from tests.client_retry.server import RetryTestServer
from tests.response_decompression.constants import DECOMPRESSED_BODY, INVALID_GZIP_BODY, UNSUPPORTED_ENCODED_BODY
from tests.streaming_decompression.constants import FIRST_OUTPUT
from tests.streaming_decompression.payloads import EncodedResponse, gated_gzip, gzip_bytes
from tests.streaming_decompression.read_actions import read_sync_prefix
from tests.streaming_decompression.server import ServerFactory
from tests.support.transport_stats import wait_for_sync_transport_stats

from .negotiation_cases import ADVERTISED_CODECS, ADVERTISEMENT, EXPLICIT_HEADERS, NegotiationOptions


@pytest.mark.parametrize("case", ADVERTISED_CODECS)
def test_sync_advertised_codecs_decode_buffered_and_streamed(
    decompression_server: ServerFactory,
    case: EncodedResponse,
) -> None:
    server = decompression_server(case)
    with foghttp.Client(auto_accept_encoding=True, trust_env=False) as client:
        buffered = client.get(server.url)
        with client.stream("GET", server.url, decode_content=True) as streamed:
            assert b"".join(streamed.iter_bytes()) == DECOMPRESSED_BODY
        assert buffered.content == DECOMPRESSED_BODY
        assert buffered.request.headers.get_list("accept-encoding") == [ADVERTISEMENT]
        assert streamed.request.headers.get_list("accept-encoding") == [ADVERTISEMENT]
        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == stats.stream_decoder_reserved_bytes == 0,
            message="decoded EOF retained negotiation request resources",
        )
    assert [request.headers.get("accept-encoding", []) for request in server.requests] == [
        [ADVERTISEMENT],
        [ADVERTISEMENT],
    ]


@pytest.mark.parametrize("options", [{}, {"auto_accept_encoding": False}], ids=["omitted", "disabled"])
def test_sync_disabled_negotiation_does_not_disable_decoding(
    decompression_server: ServerFactory,
    options: NegotiationOptions,
) -> None:
    encoded = gzip_bytes(DECOMPRESSED_BODY)
    server = decompression_server(EncodedResponse(encoded))
    with foghttp.Client(trust_env=False, **options) as client:
        buffered = client.get(server.url)
        with client.stream("GET", server.url, decode_content=True) as decoded:
            assert b"".join(decoded.iter_bytes()) == DECOMPRESSED_BODY
        with client.stream("GET", server.url) as raw:
            assert b"".join(raw.iter_bytes()) == encoded
        assert buffered.content == DECOMPRESSED_BODY
    assert all("accept-encoding" not in request.headers for request in server.requests)
    assert "accept-encoding" not in buffered.request.headers
    assert "accept-encoding" not in decoded.request.headers
    assert "accept-encoding" not in raw.request.headers


def test_sync_per_call_overrides_and_raw_mode(decompression_server: ServerFactory) -> None:
    encoded = gzip_bytes(DECOMPRESSED_BODY)
    server = decompression_server(EncodedResponse(encoded))
    with foghttp.Client(auto_accept_encoding=True, trust_env=False) as client:
        disabled = client.request("GET", server.url, auto_accept_encoding=False)
        with client.stream("GET", server.url, decode_content=True, auto_accept_encoding=False) as decoded:
            assert b"".join(decoded.iter_bytes()) == DECOMPRESSED_BODY
        with client.stream("GET", server.url, auto_accept_encoding=True) as raw:
            assert b"".join(raw.iter_bytes()) == encoded
        with client.stream("GET", server.url, decode_content=False, headers={"Accept-Encoding": "gzip"}) as explicit:
            assert b"".join(explicit.iter_bytes()) == encoded
            assert explicit.headers["content-encoding"] == "gzip"
        assert disabled.content == DECOMPRESSED_BODY
    with foghttp.Client(trust_env=False) as client:
        enabled = client.request("GET", server.url, auto_accept_encoding=True)
        with client.stream("GET", server.url, decode_content=True, auto_accept_encoding=True) as decoded_enabled:
            assert b"".join(decoded_enabled.iter_bytes()) == DECOMPRESSED_BODY
        assert enabled.content == DECOMPRESSED_BODY
    assert [request.headers.get("accept-encoding", []) for request in server.requests] == [
        [],
        [],
        [],
        ["gzip"],
        [ADVERTISEMENT],
        [ADVERTISEMENT],
    ]
    assert decoded_enabled.request.headers.get_list("accept-encoding") == [ADVERTISEMENT]


@pytest.mark.parametrize("method", ["get", "head", "post", "query", "put", "patch", "delete"])
def test_sync_convenience_methods_forward_per_call_override(sync_http_server: str, method: str) -> None:
    with foghttp.Client(trust_env=False) as client:
        response = getattr(client, method)(sync_http_server, auto_accept_encoding=True)
    assert response.status_code == HTTPStatus.OK
    assert response.request.method == method.upper()
    assert response.request.headers.get_list("accept-encoding") == [ADVERTISEMENT]


@pytest.mark.parametrize(("headers", "expected"), EXPLICIT_HEADERS)
def test_sync_explicit_headers_survive_buffered_and_stream_projection(
    decompression_server: ServerFactory,
    headers: list[tuple[str, str]],
    expected: list[str],
) -> None:
    server = decompression_server(EncodedResponse(DECOMPRESSED_BODY, encodings=()))
    with foghttp.Client(auto_accept_encoding=True, trust_env=False) as client:
        buffered = client.get(server.url, headers=headers)
        with client.stream("GET", server.url, decode_content=True, headers=headers) as streamed:
            assert b"".join(streamed.iter_bytes()) == DECOMPRESSED_BODY
        assert buffered.content == DECOMPRESSED_BODY
    assert [request.headers.get("accept-encoding", []) for request in server.requests] == [expected, expected]
    assert buffered.request.headers.get_list("accept-encoding") == expected
    assert streamed.request.headers.get_list("accept-encoding") == expected


def test_sync_repeated_direct_send_inherits_without_mutating_request(sync_http_proxy: SyncHTTPProxy) -> None:
    request = foghttp.Request(
        "POST",
        sync_http_proxy.base_url,
        headers={"X-Caller": "original"},
        content=b"replayable",
        extensions={"attempt-tag": "original"},
    )
    original_headers = request.headers.multi_items()
    with (
        foghttp.Client(auto_accept_encoding=True, trust_env=False) as enabled,
        foghttp.Client(trust_env=False) as disabled,
    ):
        first = enabled.send(request, auto_accept_encoding=True)
        second = enabled.send(request, auto_accept_encoding=False)
        inherited = enabled.send(request, auto_accept_encoding=None)
        other_client = disabled.send(request)
    assert [request.headers.get("accept-encoding", []) for request in sync_http_proxy.requests] == [
        [ADVERTISEMENT],
        [],
        [ADVERTISEMENT],
        [],
    ]
    assert first.request.headers.get_list("accept-encoding") == [ADVERTISEMENT]
    assert "accept-encoding" not in second.request.headers
    assert inherited.request.headers.get_list("accept-encoding") == [ADVERTISEMENT]
    assert "accept-encoding" not in other_client.request.headers
    assert [wire.body for wire in sync_http_proxy.requests] == [b"replayable"] * 4
    assert request.headers.multi_items() == original_headers
    assert request.auto_accept_encoding is None
    assert request.content == b"replayable"
    assert dict(request.extensions) == {"attempt-tag": "original"}


@pytest.mark.parametrize("builder_enabled", [False, True], ids=["built-disabled", "built-enabled"])
def test_sync_built_request_keeps_constructing_client_policy(
    decompression_server: ServerFactory,
    *,
    builder_enabled: bool,
) -> None:
    server = decompression_server(EncodedResponse(DECOMPRESSED_BODY, encodings=()))
    with (
        foghttp.Client(auto_accept_encoding=builder_enabled, trust_env=False) as builder,
        foghttp.Client(auto_accept_encoding=not builder_enabled, trust_env=False) as sender,
    ):
        request = builder.build_request("GET", server.url)
        original_headers = request.headers.multi_items()
        first = sender.send(request)
        overridden = sender.send(request, auto_accept_encoding=not builder_enabled)
        restored = sender.send(request)
    expected = [ADVERTISEMENT] if builder_enabled else []
    opposite = [] if builder_enabled else [ADVERTISEMENT]
    assert [wire.headers.get("accept-encoding", []) for wire in server.requests] == [expected, opposite, expected]
    assert first.request.headers.get_list("accept-encoding") == expected
    assert overridden.request.headers.get_list("accept-encoding") == opposite
    assert restored.request.headers.get_list("accept-encoding") == expected
    assert request.auto_accept_encoding is builder_enabled
    assert request.headers.multi_items() == original_headers
    assert "accept-encoding" not in request.headers


@pytest.mark.parametrize("built", [False, True], ids=["direct", "built"])
def test_sync_auth_sees_and_can_override_generated_header(
    decompression_server: ServerFactory,
    *,
    built: bool,
) -> None:
    server = decompression_server(EncodedResponse(DECOMPRESSED_BODY, encodings=()))
    calls: list[AuthRequest] = []

    def authenticate(request: AuthRequest) -> dict[str, str]:
        calls.append(request)
        return {"Accept-Encoding": "identity", "Authorization": "Bearer signed-identity"}

    with foghttp.Client(auto_accept_encoding=True, auth=authenticate, trust_env=False) as client:
        request = client.build_request("GET", server.url) if built else foghttp.Request("GET", server.url)
        response = client.send(request)
    assert [foghttp.Headers(call.headers).get_list("accept-encoding") for call in calls] == [[ADVERTISEMENT]]
    assert server.requests[0].headers["accept-encoding"] == ["identity"]
    assert server.requests[0].headers["authorization"] == ["Bearer signed-identity"]
    assert response.request.headers.get_list("accept-encoding") == ["identity"]
    assert "accept-encoding" not in request.headers


def test_sync_auth_precedence_and_recorded_removal(decompression_server: ServerFactory) -> None:
    server = decompression_server(EncodedResponse(DECOMPRESSED_BODY, encodings=()))

    def authenticate(_request: AuthRequest) -> dict[str, str]:
        return {"Accept-Encoding": "br"}

    with foghttp.Client(
        auto_accept_encoding=True,
        headers={"Accept-Encoding": "gzip"},
        auth=authenticate,
        trust_env=False,
    ) as client:
        inherited = client.get(server.url)
        explicit = client.get(server.url, headers={"Accept-Encoding": ""})
        removed = client.build_request("GET", server.url)
        del removed.headers["Accept-Encoding"]
        omitted = client.send(removed)
        disabled = client.get(server.url, auto_accept_encoding=False)
    assert [wire.headers.get("accept-encoding", []) for wire in server.requests] == [["br"], [""], [], ["br"]]
    assert inherited.request.headers.get_list("accept-encoding") == ["br"]
    assert explicit.request.headers.get_list("accept-encoding") == [""]
    assert "accept-encoding" not in omitted.request.headers
    assert disabled.request.headers.get_list("accept-encoding") == ["br"]
    assert "accept-encoding" not in removed.headers


@pytest.mark.parametrize("replacement", [[], [("aCcEpT-EnCoDiNg", "identity")]], ids=["removed", "explicit"])
def test_sync_replaced_headers_remain_authoritative(
    decompression_server: ServerFactory,
    replacement: list[tuple[str, str]],
) -> None:
    server = decompression_server(EncodedResponse(DECOMPRESSED_BODY, encodings=()))

    def authenticate(_request: AuthRequest) -> dict[str, str]:
        return {"Accept-Encoding": "br"}

    with foghttp.Client(
        auto_accept_encoding=True,
        headers={"Accept-Encoding": "gzip"},
        auth=authenticate,
        trust_env=False,
    ) as client:
        request = client.build_request("GET", server.url)
        request.headers = foghttp.Headers(replacement)
        response = client.send(request)
    expected = foghttp.Headers(replacement).get_list("accept-encoding")
    assert server.requests[0].headers.get("accept-encoding", []) == expected
    assert response.request.headers.get_list("accept-encoding") == expected
    assert request.headers.multi_items() == replacement


def test_sync_negotiation_does_not_make_upload_replayable(retry_server: RetryTestServer) -> None:
    content = iter([b"one-shot"])
    with foghttp.Client(
        auto_accept_encoding=True,
        retry=foghttp.RetryPolicy(retries=1, backoff=0, jitter=0),
        trust_env=False,
    ) as client:
        response = client.query(retry_server.url + STATUS_THEN_OK_PATH, content=content)
        assert client.stats().active_requests == 0
    requests = retry_server.snapshot().requests_for(STATUS_THEN_OK_PATH)
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert len(requests) == 1
    assert requests[0].body == b"one-shot"
    assert requests[0].accept_encoding == ADVERTISEMENT
    assert list(content) == []


@pytest.mark.parametrize("path", [STATUS_THEN_OK_PATH, CLOSE_THEN_OK_PATH], ids=["status-retry", "network-retry"])
def test_sync_retry_auth_none_restores_generated_baseline(retry_server: RetryTestServer, path: str) -> None:
    calls: list[AuthRequest] = []

    def authenticate(request: AuthRequest) -> dict[str, str] | None:
        calls.append(request)
        if len(calls) == 1:
            return {"Accept-Encoding": "identity", "Authorization": "Bearer first-attempt"}
        return None

    with foghttp.Client(
        auto_accept_encoding=True,
        auth=authenticate,
        retry=foghttp.RetryPolicy(retries=1, backoff=0, jitter=0),
        trust_env=False,
    ) as client:
        response = client.get(retry_server.url + path)
        assert client.stats().active_requests == 0
    assert response.content == b"ok"
    assert [foghttp.Headers(call.headers).get_list("accept-encoding") for call in calls] == [
        [ADVERTISEMENT],
        [ADVERTISEMENT],
    ]
    assert [call.redirect_hop for call in calls] == [0, 0]
    assert [wire.authorization for wire in retry_server.snapshot().requests_for(path)] == ["Bearer first-attempt", None]
    assert [wire.accept_encoding for wire in retry_server.snapshot().requests_for(path)] == ["identity", ADVERTISEMENT]
    assert response.request.headers.get_list("accept-encoding") == [ADVERTISEMENT]
    assert "authorization" not in response.request.headers


@pytest.mark.parametrize("cross_origin", [False, True], ids=["same-origin", "cross-origin"])
def test_sync_redirect_preserves_ordinary_default_and_wire_snapshots(
    sync_http_proxy: SyncHTTPProxy,
    decompression_server: ServerFactory,
    *,
    cross_origin: bool,
) -> None:
    target = decompression_server(EncodedResponse(DECOMPRESSED_BODY, encodings=()))
    location = f"{target.url}/final" if cross_origin else f"{sync_http_proxy.base_url}/final"
    url = f"{sync_http_proxy.base_url}{PROXY_REDIRECT_PATH}?location={location}"
    with foghttp.Client(auto_accept_encoding=True, follow_redirects=True, trust_env=False) as client:
        response = client.get(url)
    wire_requests = [*sync_http_proxy.requests, *target.requests]
    snapshots = [*[hop.request for hop in response.history], response.request]
    assert len(snapshots) == len(wire_requests)
    for snapshot, wire in zip(snapshots, wire_requests, strict=True):
        assert (
            snapshot.headers.get_list("accept-encoding") == wire.headers.get("accept-encoding", []) == [ADVERTISEMENT]
        )
    assert response.request.url == location


def test_sync_redirect_strips_sensitive_default_after_auth_returns_none(
    sync_http_proxy: SyncHTTPProxy,
    decompression_server: ServerFactory,
) -> None:
    target = decompression_server(EncodedResponse(DECOMPRESSED_BODY, encodings=()))
    cross_origin = f"{sync_http_proxy.base_url}{PROXY_REDIRECT_PATH}?location={target.url}"
    url = f"{sync_http_proxy.base_url}{PROXY_REDIRECT_PATH}?location={cross_origin}"
    calls: list[AuthRequest] = []

    def authenticate(request: AuthRequest) -> dict[str, str] | None:
        calls.append(request)
        if request.redirect_hop == 0:
            return {"Accept-Encoding": "identity", "Authorization": "Bearer first-hop"}
        return None

    with foghttp.Client(
        auto_accept_encoding=True,
        auth=authenticate,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        response = client.get(url)
    wire_requests = [*sync_http_proxy.requests, *target.requests]
    snapshots = [*[hop.request for hop in response.history], response.request]
    assert [wire.headers.get("accept-encoding", []) for wire in wire_requests] == [["identity"], [ADVERTISEMENT], []]
    assert [snapshot.headers.get_list("accept-encoding") for snapshot in snapshots] == [
        wire.headers.get("accept-encoding", []) for wire in wire_requests
    ]
    assert [call.redirect_hop for call in calls] == [0, 1]
    assert [foghttp.Headers(call.headers).get_list("accept-encoding") for call in calls] == [
        [ADVERTISEMENT],
        [ADVERTISEMENT],
    ]
    assert "authorization" not in target.requests[0].headers
    assert "authorization" not in response.request.headers


def test_sync_range_keeps_compressed_rejection_and_raw_escape(decompression_server: ServerFactory) -> None:
    encoded = gzip_bytes(DECOMPRESSED_BODY)
    server = decompression_server(EncodedResponse(encoded, status=HTTPStatus.PARTIAL_CONTENT))
    with foghttp.Client(auto_accept_encoding=True, trust_env=False) as client:
        with (
            pytest.raises(foghttp.ResponseDecodingError),
            client.stream("GET", server.url, headers={"Range": "bytes=0-9"}, decode_content=True),
        ):
            pytest.fail("compressed 206 was exposed in decoded mode")
        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == stats.stream_decoder_reserved_bytes == 0,
            message="compressed 206 leaked resources",
        )
        with client.stream("GET", server.url, headers={"Range": "bytes=0-9"}) as raw:
            assert raw.status_code == HTTPStatus.PARTIAL_CONTENT
            assert b"".join(raw.iter_bytes()) == encoded
    assert server.requests[0].headers["accept-encoding"] == [ADVERTISEMENT]
    assert "accept-encoding" not in server.requests[1].headers


def test_sync_identity_range_remains_valid(decompression_server: ServerFactory) -> None:
    server = decompression_server(EncodedResponse(DECOMPRESSED_BODY, ("identity",), HTTPStatus.PARTIAL_CONTENT))
    with (
        foghttp.Client(auto_accept_encoding=True, trust_env=False) as client,
        client.stream(
            "GET",
            server.url,
            headers={"Range": "bytes=0-9", "Accept-Encoding": "identity"},
            decode_content=True,
        ) as response,
    ):
        assert response.status_code == HTTPStatus.PARTIAL_CONTENT
        assert b"".join(response.iter_bytes()) == DECOMPRESSED_BODY
    assert server.requests[0].headers["accept-encoding"] == ["identity"]
    assert server.requests[0].headers["range"] == ["bytes=0-9"]


@pytest.mark.parametrize(
    ("method", "status"),
    [
        ("HEAD", HTTPStatus.OK),
        ("GET", HTTPStatus.NO_CONTENT),
        ("GET", HTTPStatus.RESET_CONTENT),
        ("GET", HTTPStatus.NOT_MODIFIED),
    ],
)
def test_sync_no_body_still_bypasses_decoder(
    decompression_server: ServerFactory,
    method: str,
    status: int,
) -> None:
    server = decompression_server(EncodedResponse(b"", ("unknown",), status))
    with foghttp.Client(
        auto_accept_encoding=True,
        limits=foghttp.Limits(max_stream_decoder_memory_bytes=0),
        trust_env=False,
    ) as client:
        buffered = client.request(method, server.url)
        with client.stream(method, server.url, decode_content=True) as streamed:
            assert b"".join(streamed.iter_bytes()) == b""
            assert streamed.status_code == status
            assert streamed.headers["content-encoding"] == "unknown"
        assert buffered.content == b""
        assert buffered.status_code == status
        assert client.stats().stream_decoder_reserved_bytes == client.stats().active_requests == 0
    assert [wire.headers.get("accept-encoding", []) for wire in server.requests] == [[ADVERTISEMENT], [ADVERTISEMENT]]


def test_sync_unexpected_coding_keeps_buffered_bypass_and_stream_error(decompression_server: ServerFactory) -> None:
    server = decompression_server(EncodedResponse(UNSUPPORTED_ENCODED_BODY, ("zstd",)))
    with foghttp.Client(auto_accept_encoding=True, trust_env=False) as client:
        response = client.get(server.url)
        assert response.content == UNSUPPORTED_ENCODED_BODY
        assert response.headers["content-encoding"] == "zstd"
        with pytest.raises(foghttp.ResponseDecodingError), client.stream("GET", server.url, decode_content=True):
            pytest.fail("unsupported coding was exposed")
        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == stats.stream_decoder_reserved_bytes == 0,
            message="unsupported coding leaked resources",
        )
        assert client.get(f"{server.url}/healthy").content == b"healthy"
    assert server.requests[0].headers["accept-encoding"] == [ADVERTISEMENT]
    assert server.requests[1].headers["accept-encoding"] == [ADVERTISEMENT]


def test_sync_invalid_body_releases_negotiated_stream(decompression_server: ServerFactory) -> None:
    server = decompression_server(EncodedResponse(INVALID_GZIP_BODY))
    with foghttp.Client(auto_accept_encoding=True, trust_env=False) as client:
        with (
            client.stream("GET", server.url, decode_content=True) as response,
            pytest.raises(foghttp.ResponseDecodingError),
        ):
            list(response.iter_bytes())
        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == stats.pending_requests == stats.stream_decoder_reserved_bytes == 0,
            message="invalid compressed body leaked resources",
        )
        assert client.get(f"{server.url}/healthy").content == b"healthy"
    assert server.requests[0].headers["accept-encoding"] == [ADVERTISEMENT]


def test_sync_early_close_releases_negotiated_decoder(decompression_server: ServerFactory) -> None:
    server = decompression_server(gated_gzip())
    with foghttp.Client(auto_accept_encoding=True, trust_env=False) as client:
        with client.stream("GET", server.url, decode_content=True) as response:
            iterator = response.iter_bytes()
            assert read_sync_prefix(iterator, len(FIRST_OUTPUT)) == FIRST_OUTPUT
            assert client.stats().stream_decoder_reserved_bytes > 0
        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == stats.stream_decoder_reserved_bytes == 0,
            message="early close leaked negotiated decoder resources",
        )
        assert client.get(f"{server.url}/healthy").content == b"healthy"
    assert server.requests[0].headers["accept-encoding"] == [ADVERTISEMENT]
