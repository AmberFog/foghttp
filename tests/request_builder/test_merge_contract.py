import pytest

from foghttp._client.request_builder.builder import RequestBuilder
from foghttp._client.request_builder.defaults import RequestBuildDefaults
from foghttp._client.request_builder.merge import RequestMergeContract
from foghttp._client.request_builder.models import RequestBuildOptions
from foghttp.headers import Headers, HeaderSource
from foghttp.messages import transport_managed_header_error
from foghttp.methods import GET
from foghttp.types import QueryParams


def test_merge_contract_combines_base_url_query_and_params_in_order() -> None:
    builder = _builder(
        base_url="https://api.example.com/v1/",
        params=[
            ("client", "default"),
            ("trace", "client"),
        ],
    )

    request = builder.build(
        RequestBuildOptions(
            method=GET,
            url="users?debug=1#profile",
            params=[
                ("trace", "request"),
                ("page", 2),
            ],
        ),
    )

    assert (
        request.url == "https://api.example.com/v1/users"
        "?debug=1&client=default&trace=client&trace=request&page=2#profile"
    )


def test_merge_contract_absolute_request_url_ignores_base_url() -> None:
    builder = _builder(
        base_url="https://internal.example.com/v1/",
        params={"client": "default"},
    )

    request = builder.build(
        RequestBuildOptions(
            method=GET,
            url="https://api.example.com/search?debug=1",
            params={"page": 2},
        ),
    )

    assert request.url == "https://api.example.com/search?debug=1&client=default&page=2"


def test_merge_contract_request_headers_override_defaults_case_insensitively() -> None:
    builder = _builder(
        headers=[
            ("Accept", "application/json"),
            ("X-Client", "default-client"),
            ("X-Trace", "client-trace"),
        ],
    )

    request = builder.build(
        RequestBuildOptions(
            method=GET,
            url="https://api.example.com/users",
            headers=[
                ("accept", "text/plain"),
                ("x-trace", "request-trace-1"),
                ("X-Trace", "request-trace-2"),
            ],
        ),
    )

    assert request.headers.multi_items() == [
        ("X-Client", "default-client"),
        ("accept", "text/plain"),
        ("x-trace", "request-trace-1"),
        ("X-Trace", "request-trace-2"),
    ]


def test_merge_contract_snapshots_user_supplied_defaults() -> None:
    default_headers = Headers([("Accept", "application/json")])
    default_tags = ["rust"]
    default_params = {"tag": default_tags}
    builder = _builder(headers=default_headers, params=default_params)

    default_headers["Accept"] = "text/plain"
    default_tags.append("python")

    request = builder.build(
        RequestBuildOptions(
            method=GET,
            url="https://api.example.com/search",
        ),
    )

    assert request.headers["accept"] == "application/json"
    assert request.url == "https://api.example.com/search?tag=rust"


def test_merge_contract_rejects_transport_managed_default_headers() -> None:
    with pytest.raises(ValueError, match=transport_managed_header_error("Host")):
        _builder(headers={"Host": "api.example.com"})


def _builder(
    *,
    base_url: str | None = None,
    headers: HeaderSource = None,
    params: QueryParams = None,
) -> RequestBuilder:
    defaults = RequestBuildDefaults.from_options(
        base_url=base_url,
        headers=headers,
        params=params,
    )
    return RequestBuilder(merge_contract=RequestMergeContract(defaults=defaults))
