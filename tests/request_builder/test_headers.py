from faker import Faker

import foghttp


def test_build_request_copies_mapping_headers(faker: Faker) -> None:
    source_headers = {"Accept": "application/json"}

    with foghttp.Client() as client:
        request = client.build_request("GET", faker.url(), headers=source_headers)
    source_headers["Accept"] = "text/plain"

    assert request.headers["accept"] == "application/json"


def test_build_request_preserves_repeated_headers_from_headers_model(faker: Faker) -> None:
    first_value, second_value, changed_value = faker.words(nb=3, unique=True)
    headers = foghttp.Headers([("X-Trace", first_value), ("x-trace", second_value)])

    with foghttp.Client() as client:
        request = client.build_request("GET", faker.url(), headers=headers)
    headers.add("x-trace", changed_value)

    assert request.headers.get_list("X-Trace") == [first_value, second_value]
    assert request.headers["x-trace"] == second_value
    assert request.headers.multi_items() == [("X-Trace", first_value), ("x-trace", second_value)]


def test_build_request_headers_are_case_insensitive(faker: Faker) -> None:
    value = "application/json"

    with foghttp.Client() as client:
        request = client.build_request("GET", faker.url(), headers={"ACCEPT": value})

    assert request.headers["accept"] == value
    assert request.headers["Accept"] == value
