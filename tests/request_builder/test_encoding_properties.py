from urllib.parse import unquote, urlencode, urlsplit

from hypothesis import given, settings

import foghttp
from foghttp.methods import GET, POST
from tests.request_builder.encoding_property_helpers import (
    FIELD_MAPPING,
    FIELD_PAIRS,
    FIELD_PROPERTY_EXAMPLES,
    PATH_SEGMENTS,
    QUERY_FRAGMENT,
    REQUEST_URL,
    URL_PROPERTY_EXAMPLES,
    decoded_body_pairs,
    decoded_query_pairs,
    expected_pairs,
    url_with_query,
)


@given(
    existing_pairs=FIELD_PAIRS,
    request_pairs=FIELD_PAIRS,
)
@settings(max_examples=URL_PROPERTY_EXAMPLES)
def test_query_params_preserve_existing_query_order_and_fragment(
    existing_pairs: list[tuple[str, object]],
    request_pairs: list[tuple[str, object]],
) -> None:
    url = url_with_query(REQUEST_URL, existing_pairs)

    with foghttp.Client() as client:
        request = client.build_request(GET, url, params=request_pairs)

    parts = urlsplit(request.url)
    assert parts.fragment == QUERY_FRAGMENT
    assert decoded_query_pairs(parts.query) == [
        *expected_pairs(existing_pairs),
        *expected_pairs(request_pairs),
    ]


@given(
    existing_pairs=FIELD_PAIRS,
    raw_pairs=FIELD_PAIRS,
)
@settings(max_examples=URL_PROPERTY_EXAMPLES)
def test_raw_query_string_is_appended_as_encoded_query(
    existing_pairs: list[tuple[str, object]],
    raw_pairs: list[tuple[str, object]],
) -> None:
    url = url_with_query(REQUEST_URL, existing_pairs)
    raw_query = f"?{urlencode(raw_pairs, doseq=True)}"

    with foghttp.Client() as client:
        request = client.build_request(GET, url, params=raw_query)

    parts = urlsplit(request.url)
    assert parts.fragment == QUERY_FRAGMENT
    assert decoded_query_pairs(parts.query) == [
        *expected_pairs(existing_pairs),
        *expected_pairs(raw_pairs),
    ]


@given(
    base_segments=PATH_SEGMENTS,
    request_segments=PATH_SEGMENTS,
    url_pairs=FIELD_PAIRS,
    client_pairs=FIELD_PAIRS,
    request_pairs=FIELD_PAIRS,
)
@settings(max_examples=URL_PROPERTY_EXAMPLES)
def test_base_url_join_preserves_query_merge_order_and_fragment(
    base_segments: list[str],
    request_segments: list[str],
    url_pairs: list[tuple[str, object]],
    client_pairs: list[tuple[str, object]],
    request_pairs: list[tuple[str, object]],
) -> None:
    base_path = "/".join(base_segments)
    request_path = "/".join(request_segments)
    base_url = f"https://api.example.com/{base_path}"
    request_url = url_with_query(f"{request_path}#{QUERY_FRAGMENT}", url_pairs)

    with foghttp.Client(base_url=base_url, params=client_pairs) as client:
        request = client.build_request(GET, request_url, params=request_pairs)

    parts = urlsplit(request.url)
    assert unquote(parts.path) == f"/{base_path}/{request_path}"
    assert parts.fragment == QUERY_FRAGMENT
    assert decoded_query_pairs(parts.query) == [
        *expected_pairs(url_pairs),
        *expected_pairs(client_pairs),
        *expected_pairs(request_pairs),
    ]


@given(data=FIELD_PAIRS)
@settings(max_examples=FIELD_PROPERTY_EXAMPLES)
def test_form_data_pairs_encode_repeated_fields(data: list[tuple[str, object]]) -> None:
    with foghttp.Client() as client:
        request = client.build_request(POST, "https://example.com/token", data=data)

    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert decoded_body_pairs(request.content) == expected_pairs(data)


@given(data=FIELD_MAPPING)
@settings(max_examples=FIELD_PROPERTY_EXAMPLES)
def test_form_data_mapping_encodes_sequence_values(data: dict[str, object]) -> None:
    with foghttp.Client() as client:
        request = client.build_request(POST, "https://example.com/token", data=data)

    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert decoded_body_pairs(request.content) == expected_pairs(data)
