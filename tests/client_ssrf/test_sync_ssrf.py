from faker import Faker
import pytest

import foghttp
from foghttp.status_codes.redirect import FOUND
from foghttp.status_codes.success import OK
from tests.redirect_helpers import redirect_to_location_url


BLOCKED_URLS = (
    pytest.param("http://127.0.0.1/", id="loopback"),
    pytest.param("http://10.0.0.1/", id="private"),
    pytest.param("http://169.254.10.20/", id="link-local"),
    pytest.param("http://169.254.169.254/latest/meta-data/", id="metadata"),
    pytest.param("http://224.0.0.1/", id="multicast"),
    pytest.param("http://192.88.99.1/", id="deprecated-special-use"),
    pytest.param("http://[2001:5::1]/", id="reserved-ietf-v6"),
    pytest.param("http://[2d00::1]/", id="reserved-global-unicast-v6"),
    pytest.param("http://[4000::1]/", id="unallocated-v6"),
    pytest.param("http://[::ffff:127.0.0.1]/", id="mapped-loopback"),
    pytest.param("http://[64:ff9b::7f00:1]/", id="nat64-loopback"),
    pytest.param("http://2130706433/", id="integer-loopback"),
    pytest.param("http://0x7f000001/", id="hex-loopback"),
    pytest.param("http://0177.0.0.1/", id="octal-loopback"),
    pytest.param("http://127.1/", id="short-loopback"),
    pytest.param("http://0x7f.1/", id="mixed-hex-loopback"),
    pytest.param("http://%31%32%37.0.0.1/", id="url-encoded-loopback"),
)


def test_sync_ssrf_policy_is_off_by_default(sync_http_server: str) -> None:
    with foghttp.Client() as client:
        response = client.get(sync_http_server)

    assert response.status_code == OK


@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_sync_ssrf_policy_blocks_non_public_ip_literals(url: str) -> None:
    with (
        foghttp.Client(ssrf=foghttp.SSRFPolicy()) as client,
        pytest.raises(foghttp.RequestError, match="SSRF policy blocked target"),
    ):
        client.get(url)


def test_sync_ssrf_policy_blocks_localhost_after_dns_resolution(
    sync_http_server: str,
) -> None:
    localhost_url = sync_http_server.replace("127.0.0.1", "localhost")

    with (
        foghttp.Client(ssrf=foghttp.SSRFPolicy()) as client,
        pytest.raises(foghttp.RequestError, match="address is not publicly routable") as exc_info,
    ):
        client.get(localhost_url)

    message = str(exc_info.value)
    assert "localhost" in message
    assert "127.0.0.1" not in message


def test_sync_ssrf_policy_still_checks_an_allowlisted_hostname_after_dns(
    sync_http_server: str,
) -> None:
    localhost_url = sync_http_server.replace("127.0.0.1", "localhost")
    policy = foghttp.SSRFPolicy(allowed_domains=("localhost",))

    with (
        foghttp.Client(ssrf=policy) as client,
        pytest.raises(foghttp.RequestError, match="address is not publicly routable"),
    ):
        client.get(localhost_url)


def test_sync_ssrf_policy_does_not_retry_a_dns_violation(sync_http_server: str) -> None:
    localhost_url = sync_http_server.replace("127.0.0.1", "localhost")
    retry = foghttp.RetryPolicy(retries=3, backoff=0, jitter=0)

    with (
        foghttp.Client(ssrf=foghttp.SSRFPolicy(), retry=retry) as client,
        pytest.raises(foghttp.RequestError) as exc_info,
    ):
        client.get(localhost_url)

    trace = exc_info.value.retry_trace
    assert trace is not None
    assert len(trace.attempts) == 1
    assert trace.attempts[0].decision is None


def test_sync_ssrf_policy_allows_an_explicit_ip_origin(sync_http_server: str) -> None:
    policy = foghttp.SSRFPolicy(allowed_origins=(sync_http_server,))

    with foghttp.Client(ssrf=policy) as client:
        response = client.get(f"{sync_http_server}/allowed")

    assert response.status_code == OK


@pytest.mark.parametrize(
    ("policy", "url", "reason"),
    [
        pytest.param(
            foghttp.SSRFPolicy(allowed_schemes=("https",)),
            "http://127.0.0.1/",
            "scheme is not allowlisted",
            id="scheme",
        ),
        pytest.param(
            foghttp.SSRFPolicy(allowed_domains=("example.com",)),
            "http://127.0.0.1/",
            "destination is not allowlisted",
            id="domain",
        ),
    ],
)
def test_sync_ssrf_policy_passes_public_allowlists_to_native_gate(
    policy: foghttp.SSRFPolicy,
    url: str,
    reason: str,
) -> None:
    with (
        foghttp.Client(ssrf=policy) as client,
        pytest.raises(foghttp.RequestError, match=reason),
    ):
        client.get(url)


def test_sync_ssrf_policy_checks_redirect_target_before_sending(
    sync_http_server: str,
    secondary_sync_http_server: str,
    faker: Faker,
) -> None:
    secret = faker.uuid4()
    location_origin = secondary_sync_http_server.replace("127.0.0.1", "localhost")
    blocked_location = f"{location_origin}/private?token={secret}"
    intermediate = redirect_to_location_url(
        sync_http_server,
        status_code=FOUND,
        location=blocked_location,
    )
    url = redirect_to_location_url(sync_http_server, status_code=FOUND, location=intermediate)
    policy = foghttp.SSRFPolicy(
        allowed_origins=(sync_http_server,),
        allowed_domains=("localhost",),
    )

    with (
        foghttp.Client(follow_redirects=True, ssrf=policy) as client,
        pytest.raises(foghttp.RequestError, match="address is not publicly routable") as exc_info,
    ):
        client.get(url)

    message = str(exc_info.value)
    assert "localhost" in message
    assert "/private" not in message
    assert secret not in message


def test_sync_ssrf_policy_error_redacts_url_credentials_and_request_target(
    faker: Faker,
) -> None:
    secret = faker.uuid4()
    url = f"http://user:{secret}@10.0.0.1/private?token={secret}"

    with (
        foghttp.Client(ssrf=foghttp.SSRFPolicy()) as client,
        pytest.raises(foghttp.RequestError) as exc_info,
    ):
        client.get(url)

    message = str(exc_info.value)
    assert "http://10.0.0.1" in message
    assert "user" not in message
    assert "/private" not in message
    assert secret not in message


def test_sync_ssrf_policy_applies_to_streaming_requests() -> None:
    with (
        foghttp.Client(ssrf=foghttp.SSRFPolicy()) as client,
        pytest.raises(foghttp.RequestError, match="SSRF policy blocked target"),
        client.stream("GET", "http://127.0.0.1/private"),
    ):
        pass


def test_sync_ssrf_policy_fails_closed_for_proxy_resolution(sync_http_server: str) -> None:
    with (
        foghttp.Client(proxy=sync_http_server, ssrf=foghttp.SSRFPolicy()) as client,
        pytest.raises(
            foghttp.RequestError,
            match="proxy transport cannot guarantee local DNS validation",
        ),
    ):
        client.get("https://example.com/")
