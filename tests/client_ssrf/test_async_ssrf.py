import pytest

import foghttp
from foghttp.status_codes.redirect import FOUND
from foghttp.status_codes.success import OK
from tests.redirect_helpers import redirect_to_location_url


async def test_async_ssrf_policy_blocks_localhost_after_dns_resolution(
    http_server: str,
) -> None:
    localhost_url = http_server.replace("127.0.0.1", "localhost")

    async with foghttp.AsyncClient(ssrf=foghttp.SSRFPolicy()) as client:
        with pytest.raises(
            foghttp.SSRFError,
            match="address is not publicly routable",
        ) as exc_info:
            await client.get(localhost_url)

    assert exc_info.value.reason is foghttp.SSRFViolationReason.NON_PUBLIC_ADDRESS


async def test_async_ssrf_policy_allows_an_explicit_ip_origin(http_server: str) -> None:
    policy = foghttp.SSRFPolicy(allowed_origins=(http_server,))

    async with foghttp.AsyncClient(ssrf=policy) as client:
        response = await client.get(f"{http_server}/allowed")

    assert response.status_code == OK


async def test_async_ssrf_policy_checks_redirect_target_before_sending(
    http_server: str,
    secondary_http_server: str,
) -> None:
    location_origin = secondary_http_server.replace("127.0.0.1", "localhost")
    blocked_location = f"{location_origin}/private"
    intermediate = redirect_to_location_url(
        http_server,
        status_code=FOUND,
        location=blocked_location,
    )
    url = redirect_to_location_url(http_server, status_code=FOUND, location=intermediate)
    policy = foghttp.SSRFPolicy(
        allowed_origins=(http_server,),
        allowed_domains=("localhost",),
    )

    async with foghttp.AsyncClient(follow_redirects=True, ssrf=policy) as client:
        with pytest.raises(foghttp.SSRFError, match="address is not publicly routable"):
            await client.get(url)


async def test_async_ssrf_policy_applies_to_streaming_requests() -> None:
    async with foghttp.AsyncClient(ssrf=foghttp.SSRFPolicy()) as client:
        with pytest.raises(foghttp.SSRFError, match="SSRF policy blocked target"):
            async with client.stream("GET", "http://127.0.0.1/private"):
                pass


async def test_async_ssrf_policy_fails_closed_for_proxy_resolution(http_server: str) -> None:
    async with foghttp.AsyncClient(proxy=http_server, ssrf=foghttp.SSRFPolicy()) as client:
        with pytest.raises(
            foghttp.SSRFError,
            match="proxy transport cannot guarantee local DNS validation",
        ) as exc_info:
            await client.get("https://example.com/")

    assert exc_info.value.reason is foghttp.SSRFViolationReason.PROXY_RESOLUTION_UNSUPPORTED
