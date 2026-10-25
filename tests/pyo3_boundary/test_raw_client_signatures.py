import inspect

from foghttp import _foghttp
from foghttp.limits import DEFAULT_MAX_TOTAL_UPLOAD_BUFFER_BYTES, DEFAULT_MAX_UPLOAD_BUFFER_BYTES


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
    "cookies_enabled",
    "ca_certificates",
    "trust_webpki_roots",
    "runtime",
    "runtime_workers",
    "http_proxy_url",
    "http_proxy_authorization",
    "https_proxy_url",
    "https_proxy_authorization",
    "auth_basic_authorization",
    "auth_hook",
    "policy_hooks",
    "retry_retries",
    "retry_backoff",
    "retry_jitter",
    "retry_statuses",
    "retry_methods",
    "retry_network_errors",
    "ssrf_allowed_schemes",
    "ssrf_allowed_origins",
    "ssrf_allowed_domains",
    "telemetry_enabled",
    "max_stream_decoded_bytes",
    "max_stream_decoder_memory_bytes",
    "max_upload_buffer_bytes",
    "max_total_upload_buffer_bytes",
)

RAW_REQUEST_KEYWORD_ONLY_PARAMETERS = (
    "method",
    "url",
    "headers",
    "auth_override_headers",
    "auth_removed_headers",
    "extensions",
    "body",
    "body_stream",
    "body_replayable",
    "use_proxy_transport",
    "proxy_policy",
    "pool_timeout",
    "read_timeout",
    "write_timeout",
    "total_timeout",
    "telemetry_request_id",
)


def test_raw_client_init_signature_is_kw_only() -> None:
    signature = inspect.signature(_foghttp.RawClient)

    assert _parameter_names(signature) == RAW_CLIENT_KEYWORD_ONLY_PARAMETERS
    assert all(parameter.kind is inspect.Parameter.KEYWORD_ONLY for parameter in signature.parameters.values())
    assert signature.parameters["max_stream_decoded_bytes"].default is None
    assert signature.parameters["max_stream_decoder_memory_bytes"].default == 128 * 1024 * 1024
    assert signature.parameters["max_upload_buffer_bytes"].default == DEFAULT_MAX_UPLOAD_BUFFER_BYTES
    assert signature.parameters["max_total_upload_buffer_bytes"].default == DEFAULT_MAX_TOTAL_UPLOAD_BUFFER_BYTES


def test_raw_request_signatures_are_kw_only() -> None:
    methods = (
        (_foghttp.RawClient.request, ()),
        (_foghttp.RawClient.request_async, ()),
        (_foghttp.RawClient.request_stream, ("decode_content",)),
        (_foghttp.RawClient.request_stream_async, ("decode_content",)),
    )

    for method, stream_parameters in methods:
        signature = inspect.signature(method)
        parameters = tuple(signature.parameters.values())

        assert parameters[0].name == "self"
        assert parameters[0].kind is inspect.Parameter.POSITIONAL_ONLY
        assert _parameter_names(signature)[1:] == (*RAW_REQUEST_KEYWORD_ONLY_PARAMETERS, *stream_parameters)
        assert all(parameter.kind is inspect.Parameter.KEYWORD_ONLY for parameter in parameters[1:])
        assert signature.parameters["extensions"].default is None
        for name in stream_parameters:
            assert signature.parameters[name].default is False


def _parameter_names(signature: inspect.Signature) -> tuple[str, ...]:
    return tuple(signature.parameters)
