from faker import Faker
import pytest

import foghttp
from foghttp.methods import GET
from foghttp.status_codes.client_error import MAX_CLIENT_ERROR_STATUS_CODE, MIN_CLIENT_ERROR_STATUS_CODE
from foghttp.status_codes.redirect import MAX_REDIRECT_STATUS_CODE, MIN_REDIRECT_STATUS_CODE
from foghttp.status_codes.server_error import MAX_SERVER_ERROR_STATUS_CODE, MIN_SERVER_ERROR_STATUS_CODE
from foghttp.status_codes.success import MAX_SUCCESS_STATUS_CODE, MIN_SUCCESS_STATUS_CODE


FLAG_NAMES = (
    "is_success",
    "is_redirect",
    "is_client_error",
    "is_server_error",
    "is_error",
)


@pytest.mark.parametrize(
    (
        "status_code",
        "expected_flags",
    ),
    [
        (MIN_SUCCESS_STATUS_CODE - 1, set()),
        (MIN_SUCCESS_STATUS_CODE, {"is_success"}),
        (MAX_SUCCESS_STATUS_CODE, {"is_success"}),
        (MIN_REDIRECT_STATUS_CODE, {"is_redirect"}),
        (MAX_REDIRECT_STATUS_CODE, {"is_redirect"}),
        (MIN_CLIENT_ERROR_STATUS_CODE, {"is_client_error", "is_error"}),
        (MAX_CLIENT_ERROR_STATUS_CODE, {"is_client_error", "is_error"}),
        (MIN_SERVER_ERROR_STATUS_CODE, {"is_server_error", "is_error"}),
        (MAX_SERVER_ERROR_STATUS_CODE, {"is_server_error", "is_error"}),
        (MAX_SERVER_ERROR_STATUS_CODE + 1, set()),
    ],
)
def test_response_status_flags(
    status_code: int,
    expected_flags: set[str],
    faker: Faker,
) -> None:
    response = _response(status_code, url=faker.url())
    actual_flags = {name for name in FLAG_NAMES if getattr(response, name)}

    assert actual_flags == expected_flags


@pytest.mark.parametrize(
    "status_code",
    [
        MIN_CLIENT_ERROR_STATUS_CODE,
        MAX_CLIENT_ERROR_STATUS_CODE,
        MIN_SERVER_ERROR_STATUS_CODE,
        MAX_SERVER_ERROR_STATUS_CODE,
    ],
)
def test_raise_for_status_raises_for_error_status_flags(
    status_code: int,
    faker: Faker,
) -> None:
    response = _response(status_code, url=faker.url())

    assert response.is_error
    with pytest.raises(foghttp.HTTPStatusError):
        response.raise_for_status()


@pytest.mark.parametrize(
    "status_code",
    [
        MIN_CLIENT_ERROR_STATUS_CODE - 1,
        MAX_SERVER_ERROR_STATUS_CODE + 1,
    ],
)
def test_raise_for_status_allows_non_error_status_flags(
    status_code: int,
    faker: Faker,
) -> None:
    response = _response(status_code, url=faker.url())

    assert not response.is_error
    response.raise_for_status()


def _response(status_code: int, *, url: str) -> foghttp.Response:
    return foghttp.Response(
        status_code=status_code,
        headers=foghttp.Headers(),
        content=b"",
        url=url,
        request=foghttp.RequestInfo(
            method=GET,
            url=url,
            headers=foghttp.Headers(),
        ),
        http_version="HTTP/1.1",
        elapsed=0.0,
    )
