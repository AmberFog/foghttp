import pytest

import foghttp
from foghttp._client.proxy import ProxyResolver
from foghttp._client.transport_requests import raw_request_options


def test_projection_keeps_generated_header_out_of_caller_owned_names() -> None:
    request = foghttp.Request("POST", "https://example.invalid", headers={"X-Token": "caller"}, content=b"payload")
    projected = raw_request_options(request, foghttp.Timeouts(), ProxyResolver.disabled(), auto_accept_encoding=True)

    assert projected.headers == [("X-Token", "caller"), ("Accept-Encoding", "gzip, deflate, br")]
    assert projected.auth_override_headers == ("x-token",)
    assert request.headers.multi_items() == [("X-Token", "caller")]
    assert projected.body.content is request.content
    assert request.auto_accept_encoding is None
    disabled = raw_request_options(request, foghttp.Timeouts(), ProxyResolver.disabled())
    assert disabled.headers == [("X-Token", "caller")]
    assert disabled.auth_override_headers is None


@pytest.mark.parametrize("value", ["", "identity", "gzip;q=0, br;q=0.3"])
def test_explicit_header_preserves_value_and_ownership(value: str) -> None:
    request = foghttp.Request("GET", "https://example.invalid", headers=[("aCcEpT-EnCoDiNg", value)])
    projected = raw_request_options(request, foghttp.Timeouts(), ProxyResolver.disabled(), auto_accept_encoding=True)
    assert projected.headers == request.headers.multi_items()
    assert projected.auth_override_headers is None


def test_existing_auth_provenance_and_removal_are_preserved() -> None:
    with foghttp.Client(auth=("user", "password"), headers={"Accept-Encoding": "identity"}) as client:
        request = client.build_request("GET", "https://example.invalid")
    del request.headers["Accept-Encoding"]
    projected = raw_request_options(request, foghttp.Timeouts(), ProxyResolver.disabled(), auto_accept_encoding=True)
    assert not projected.headers
    assert projected.auth_override_headers == ()
    assert projected.auth_removed_headers == ("accept-encoding",)


def test_generated_default_does_not_override_builder_auth_provenance() -> None:
    with foghttp.Client(auth=("user", "password"), headers={"X-Default": "client"}) as client:
        request = client.build_request("GET", "https://example.invalid", headers={"X-Request": "request"})
    projected = raw_request_options(request, foghttp.Timeouts(), ProxyResolver.disabled(), auto_accept_encoding=True)
    assert projected.auth_override_headers == ("x-request",)
    assert projected.auth_removed_headers == ()
    assert projected.headers[-1] == ("Accept-Encoding", "gzip, deflate, br")
    assert "Accept-Encoding" not in request.headers
