from faker import Faker

import foghttp
from foghttp.methods import GET


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
    assert repr(request) == "Request('GET', 'https://example.com/users')"
