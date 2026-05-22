from faker import Faker

import foghttp
from foghttp._request_body import request_body
from foghttp.methods import GET, POST
from tests.request_factories import non_replayable_request


def test_request_normalizes_method_url_and_copies_headers(faker: Faker) -> None:
    initial_value, changed_value = faker.words(nb=2, unique=True)
    content = faker.sentence().encode()
    headers = foghttp.Headers([("x-repeat", initial_value)])

    request = foghttp.Request(
        GET.lower(),
        "HTTPS://Example.COM:443/users",
        headers=headers,
        content=content,
    )
    headers.add("x-repeat", changed_value)

    assert request.method == GET
    assert request.url == "https://example.com/users"
    assert request.headers.get_list("x-repeat") == [initial_value]
    assert request.content == content
    assert request_body(request).replayable is True
    assert repr(request) == "Request('GET', 'https://example.com/users')"


def test_request_can_carry_internal_non_replayable_body(faker: Faker) -> None:
    content = faker.binary(length=16)

    request = non_replayable_request(
        POST,
        faker.url(),
        content=content,
    )

    assert request.content == content
    assert request_body(request).replayable is False


def test_empty_internal_request_body_stays_replayable(faker: Faker) -> None:
    request = non_replayable_request(
        POST,
        faker.url(),
        content=b"",
    )

    assert request.content == b""
    assert request_body(request).replayable is True


def test_assigning_request_content_restores_buffered_replayability(faker: Faker) -> None:
    request = non_replayable_request(
        POST,
        faker.url(),
        content=faker.binary(length=16),
    )

    request.content = faker.binary(length=8)

    assert request_body(request).replayable is True
