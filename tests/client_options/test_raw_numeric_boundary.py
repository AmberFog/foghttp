import math

from faker import Faker
import pytest

from foghttp import _foghttp
from foghttp.methods import GET


KEEPALIVE = True
FOLLOW_REDIRECTS = False
TRUST_WEBPKI_ROOTS = True
CUSTOM_ONLY_TRUST_WEBPKI_ROOTS = False
REQUEST_BODY_REPLAYABLE = True


def test_raw_client_rejects_empty_custom_only_tls_trust_store() -> None:
    with pytest.raises(
        _foghttp.FogHttpError,
        match="TLS trust store is empty; enable WebPKI roots or provide CA certificates",
    ):
        _foghttp.RawClient(
            1,
            None,
            1,
            1,
            None,
            None,
            30.0,
            KEEPALIVE,
            2.0,
            FOLLOW_REDIRECTS,
            20,
            (),
            CUSTOM_ONLY_TRUST_WEBPKI_ROOTS,
            None,
        )


def test_raw_client_rejects_invalid_idle_timeout_without_panic() -> None:
    with pytest.raises(
        ValueError,
        match=r"Limits\.idle_timeout must be a finite number between 0 and",
    ):
        _foghttp.RawClient(
            1,
            None,
            1,
            1,
            None,
            None,
            math.nan,
            KEEPALIVE,
            2.0,
            FOLLOW_REDIRECTS,
            20,
            (),
            TRUST_WEBPKI_ROOTS,
            None,
        )


def test_raw_client_rejects_too_large_active_request_limit_without_panic() -> None:
    with pytest.raises(
        ValueError,
        match=r"Limits\.max_active_requests must be an integer between 0 and",
    ):
        _foghttp.RawClient(
            2**31,
            None,
            1,
            1,
            None,
            None,
            30.0,
            KEEPALIVE,
            2.0,
            FOLLOW_REDIRECTS,
            20,
            (),
            TRUST_WEBPKI_ROOTS,
            None,
        )


def test_raw_client_sync_request_rejects_invalid_timeout_without_panic(faker: Faker) -> None:
    raw_client = _raw_client()
    try:
        with pytest.raises(
            ValueError,
            match=r"Timeouts\.pool must be a finite number between 0 and",
        ):
            raw_client.request(GET, faker.url(), [], None, REQUEST_BODY_REPLAYABLE, math.nan, 1.0, 1.0)
    finally:
        raw_client.close()


def test_raw_client_sync_request_rejects_invalid_read_timeout_without_panic(faker: Faker) -> None:
    raw_client = _raw_client()
    try:
        with pytest.raises(
            ValueError,
            match=r"Timeouts\.read must be a finite number between 0 and",
        ):
            raw_client.request(GET, faker.url(), [], None, REQUEST_BODY_REPLAYABLE, 1.0, math.nan, 1.0)
    finally:
        raw_client.close()


async def test_raw_client_async_request_rejects_invalid_timeout_without_panic(
    faker: Faker,
) -> None:
    raw_client = _raw_client()
    try:
        with pytest.raises(
            ValueError,
            match=r"Timeouts\.total must be a finite number between 0 and",
        ):
            raw_client.request_async(GET, faker.url(), [], None, REQUEST_BODY_REPLAYABLE, 1.0, 1.0, math.inf)
    finally:
        raw_client.close()


def _raw_client() -> _foghttp.RawClient:
    return _foghttp.RawClient(
        1,
        None,
        1,
        1,
        None,
        None,
        30.0,
        KEEPALIVE,
        2.0,
        FOLLOW_REDIRECTS,
        20,
        (),
        TRUST_WEBPKI_ROOTS,
        None,
    )
