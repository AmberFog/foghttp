from urllib.parse import urlencode

from faker import Faker
import orjson
import pytest

import foghttp
from foghttp.methods import QUERY
from foghttp.status_codes.client_error import NOT_FOUND
from foghttp.status_codes.redirect import TEMPORARY_REDIRECT
from foghttp.status_codes.success import OK
from foghttp.telemetry import TelemetryConfig
from tests.client_query.assertions import assert_query_echo
from tests.client_telemetry.models import RecordingTelemetrySink
from tests.redirect_helpers import SECURITY_HEADERS_PATH


def test_sync_query_supports_json_body(
    sync_http_server: str,
    faker: Faker,
) -> None:
    body = {"filter": faker.sentence()}

    with foghttp.Client() as client:
        response = client.query(
            f"{sync_http_server}{SECURITY_HEADERS_PATH}",
            json=body,
        )

    assert_query_echo(
        response,
        body=orjson.dumps(body).decode(),
        content_type="application/json",
    )


def test_sync_query_supports_form_body(
    sync_http_server: str,
    faker: Faker,
) -> None:
    body = {"filter": faker.word(), "page": faker.random_int(min=1, max=100)}

    with foghttp.Client() as client:
        response = client.query(
            f"{sync_http_server}{SECURITY_HEADERS_PATH}",
            data=body,
        )

    assert_query_echo(
        response,
        body=urlencode(body),
        content_type="application/x-www-form-urlencoded",
    )


def test_sync_query_supports_text_body(
    sync_http_server: str,
    faker: Faker,
) -> None:
    body = faker.sentence()

    with foghttp.Client() as client:
        response = client.query(
            f"{sync_http_server}{SECURITY_HEADERS_PATH}",
            headers={"content-type": "text/plain"},
            content=body,
        )

    assert_query_echo(response, body=body, content_type="text/plain")


def test_sync_query_supports_bytes_body(
    sync_http_server: str,
    faker: Faker,
) -> None:
    body = faker.word().encode()

    with foghttp.Client() as client:
        response = client.query(
            f"{sync_http_server}{SECURITY_HEADERS_PATH}",
            headers={"content-type": "application/octet-stream"},
            content=body,
        )

    assert_query_echo(
        response,
        body=body.decode(),
        content_type="application/octet-stream",
    )


def test_sync_query_preserves_metadata_and_telemetry(
    sync_http_server: str,
    faker: Faker,
) -> None:
    url_secret = faker.sha256()
    body_secret = faker.sha256()
    sink = RecordingTelemetrySink()

    with foghttp.Client(telemetry=TelemetryConfig(sink=sink)) as client:
        request = client.build_request(
            QUERY.lower(),
            f"{sync_http_server}/status/{OK}?token={url_secret}",
            json={"filter": body_secret},
        )
        representation = repr(request)
        response = client.send(request)

    assert request.method == QUERY
    assert response.request.method == QUERY
    assert QUERY in representation
    assert url_secret not in representation
    assert body_secret not in representation
    assert sink.events
    assert {event.method for event in sink.events} == {QUERY}
    assert body_secret not in repr(sink.events)
    assert all(url_secret not in (event.redacted_url or "") for event in sink.events)


def test_sync_query_status_error_preserves_method_and_redacts_sensitive_data(
    sync_http_server: str,
    faker: Faker,
) -> None:
    url_secret = faker.sha256()
    body_secret = faker.sha256()

    with foghttp.Client() as client:
        response = client.request(
            QUERY,
            f"{sync_http_server}/status/{NOT_FOUND}?token={url_secret}",
            headers={"content-type": "text/plain"},
            content=body_secret,
        )

    with pytest.raises(foghttp.HTTPStatusError) as exc_info:
        response.raise_for_status()

    assert str(exc_info.value).startswith(f"{QUERY} ")
    assert url_secret not in str(exc_info.value)
    assert body_secret not in str(exc_info.value)


def test_sync_query_works_with_stream_api(sync_http_server: str, faker: Faker) -> None:
    body = faker.sentence()

    with (
        foghttp.Client(follow_redirects=True) as client,
        client.stream(
            QUERY,
            f"{sync_http_server}/redirect/{TEMPORARY_REDIRECT}",
            headers={"content-type": "text/plain"},
            content=body,
        ) as response,
    ):
        payload = orjson.loads(b"".join(response.iter_bytes()))

    assert response.request.method == QUERY
    assert payload["request_line"] == f"{QUERY} /final HTTP/1.1"
    assert payload["body"] == body
