from faker import Faker
import pytest

from foghttp._client.raw import close_raw_client, send_raw_request
from foghttp.errors import RequestError
from foghttp.timeouts import Timeouts

from .helpers import create_test_raw_client


def test_raw_client_close_is_idempotent() -> None:
    raw_client = create_test_raw_client()

    close_raw_client(raw_client)
    close_raw_client(raw_client)


def test_raw_client_rejects_requests_after_close_without_leaking_metrics(faker: Faker) -> None:
    raw_client = create_test_raw_client()
    close_raw_client(raw_client)

    with pytest.raises(RequestError, match="client is closed"):
        send_raw_request(
            raw_client=raw_client,
            method="GET",
            url=faker.url(),
            headers=[],
            body=None,
            timeouts=Timeouts(),
        )

    assert raw_client.stats().active_connections == 0
