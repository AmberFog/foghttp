from faker import Faker
import pytest

from foghttp._client.proxy import ProxyTransportPolicy
from foghttp._client.raw.lifecycle import close_raw_client
from foghttp._client.raw.requests import RawRequestOptions, send_raw_request
from foghttp.errors import RequestError
from foghttp.methods import GET
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
            request=RawRequestOptions(
                method=GET,
                url=faker.url(),
                headers=[],
                body=None,
                body_replayable=True,
                use_proxy_transport=False,
                proxy_policy=ProxyTransportPolicy.DIRECT,
                timeouts=Timeouts(),
            ),
        )

    assert raw_client.stats().active_requests == 0
