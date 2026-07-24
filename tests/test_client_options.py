import pytest

import foghttp


def test_client_rejects_negative_max_redirects() -> None:
    with pytest.raises(ValueError, match="max_redirects must be greater than or equal to 0"):
        foghttp.Client(max_redirects=-1)


def test_async_client_rejects_negative_max_redirects() -> None:
    with pytest.raises(ValueError, match="max_redirects must be greater than or equal to 0"):
        foghttp.AsyncClient(max_redirects=-1)


def test_limits_reject_negative_max_response_body_size() -> None:
    with pytest.raises(
        ValueError,
        match=r"Limits\.max_response_body_size must be an integer between 0 and",
    ):
        foghttp.Limits(max_response_body_size=-1)


def test_limits_reject_negative_max_buffered_response_bytes() -> None:
    with pytest.raises(
        ValueError,
        match=r"Limits\.max_buffered_response_bytes must be an integer between 0 and",
    ):
        foghttp.Limits(max_buffered_response_bytes=-1)


def test_client_accepts_opt_in_cookies() -> None:
    client = foghttp.Client(cookies=True)
    client.close()


def test_client_rejects_unsupported_http_versions() -> None:
    with pytest.raises(NotImplementedError, match=r"only HTTP/1\.1 is supported in the MVP"):
        foghttp.Client(http_versions=["HTTP/2"])


def test_client_accepts_explicit_http_1_1() -> None:
    client = foghttp.Client(http_versions=["HTTP/1.1"])
    client.close()
