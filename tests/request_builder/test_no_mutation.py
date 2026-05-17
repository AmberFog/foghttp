from copy import deepcopy

from faker import Faker

import foghttp
from foghttp.methods import GET, POST


def test_build_request_does_not_mutate_user_inputs(faker: Faker) -> None:
    headers = foghttp.Headers([("Accept", "application/json"), ("X-Trace", faker.word())])
    params = {"tag": ["rust", "python"], "q": faker.word()}
    payload = {"name": faker.name(), "tags": [faker.word(), faker.word()]}
    expected_headers = headers.multi_items()
    expected_params = deepcopy(params)
    expected_payload = deepcopy(payload)

    with foghttp.Client() as client:
        client.build_request(
            POST,
            faker.url(),
            headers=headers,
            params=params,
            json=payload,
        )

    assert headers.multi_items() == expected_headers
    assert params == expected_params
    assert payload == expected_payload


def test_build_request_does_not_mutate_pair_params(faker: Faker) -> None:
    params = [("tag", ["rust", "python"]), ("q", faker.word())]
    expected_params = deepcopy(params)

    with foghttp.Client() as client:
        client.build_request(GET, faker.url(), params=params)

    assert params == expected_params
