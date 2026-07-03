import inspect

from foghttp import _foghttp


RAW_CLIENT_KEYWORD_ONLY_PARAMETERS = (
    "max_active_requests",
    "max_active_requests_per_origin",
    "max_connections",
    "max_connections_per_host",
    "max_idle_connections_per_host",
    "max_pending_requests",
    "max_response_body_size",
    "max_buffered_response_bytes",
    "idle_timeout",
    "keepalive",
    "connect_timeout",
    "follow_redirects",
    "max_redirects",
    "ca_certificates",
    "trust_webpki_roots",
    "runtime",
    "runtime_workers",
    "http_proxy_url",
    "http_proxy_authorization",
    "https_proxy_url",
    "https_proxy_authorization",
)

RAW_REQUEST_KEYWORD_ONLY_PARAMETERS = (
    "method",
    "url",
    "headers",
    "body",
    "body_stream",
    "body_replayable",
    "use_proxy_transport",
    "proxy_policy",
    "pool_timeout",
    "read_timeout",
    "write_timeout",
    "total_timeout",
)


def test_raw_client_init_signature_is_kw_only() -> None:
    signature = inspect.signature(_foghttp.RawClient)

    assert _parameter_names(signature) == RAW_CLIENT_KEYWORD_ONLY_PARAMETERS
    assert all(parameter.kind is inspect.Parameter.KEYWORD_ONLY for parameter in signature.parameters.values())


def test_raw_request_signatures_are_kw_only() -> None:
    methods = (
        _foghttp.RawClient.request,
        _foghttp.RawClient.request_async,
        _foghttp.RawClient.request_stream,
        _foghttp.RawClient.request_stream_async,
    )

    for method in methods:
        signature = inspect.signature(method)
        parameters = tuple(signature.parameters.values())

        assert parameters[0].name == "self"
        assert parameters[0].kind is inspect.Parameter.POSITIONAL_ONLY
        assert _parameter_names(signature)[1:] == RAW_REQUEST_KEYWORD_ONLY_PARAMETERS
        assert all(parameter.kind is inspect.Parameter.KEYWORD_ONLY for parameter in parameters[1:])


def _parameter_names(signature: inspect.Signature) -> tuple[str, ...]:
    return tuple(signature.parameters)
