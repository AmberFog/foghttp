from faker import Faker
import pytest

from foghttp._client.proxy import ProxyTarget, ProxyUrl


HTTP_DEFAULT_PORT = 80
TEST_PROXY_PORT = 8080


def test_proxy_url_normalizes_endpoint_without_credentials(faker: Faker) -> None:
    username = faker.user_name()
    hidden_value = faker.pystr(min_chars=12, max_chars=12)
    proxy = ProxyUrl.parse(f"http://{username}:{hidden_value}@Proxy.Example:080")
    representation = repr(proxy)

    assert proxy.host == "proxy.example"
    assert proxy.port == HTTP_DEFAULT_PORT
    assert proxy.endpoint_netloc == "proxy.example:80"
    assert proxy.endpoint_url == "http://proxy.example:80"
    assert proxy.redacted_url == "http://<redacted>@proxy.example:80"
    assert username not in representation
    assert hidden_value not in representation


def test_proxy_url_normalizes_ipv6_endpoint() -> None:
    proxy = ProxyUrl.parse("http://[::1]:8080")

    assert proxy.host == "::1"
    assert proxy.port == TEST_PROXY_PORT
    assert proxy.endpoint_netloc == "[::1]:8080"
    assert proxy.endpoint_url == "http://[::1]:8080"


def test_proxy_url_normalizes_root_path_endpoint() -> None:
    proxy = ProxyUrl.parse("http://proxy.example/")

    assert proxy.host == "proxy.example"
    assert proxy.port == HTTP_DEFAULT_PORT
    assert proxy.endpoint_netloc == "proxy.example:80"
    assert proxy.endpoint_url == "http://proxy.example:80"


@pytest.mark.parametrize(
    ("value", "source"),
    [
        pytest.param("http://proxy.example:0", "proxy URL", id="proxy-url"),
        pytest.param("https://api.example.com:0/items", "target URL", id="target-url"),
    ],
)
def test_proxy_urls_reject_zero_ports(value: str, source: str) -> None:
    parser = ProxyUrl.parse if source == "proxy URL" else ProxyTarget.parse

    with pytest.raises(ValueError, match=f"{source} port must be between 1 and 65535"):
        parser(value)


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("http://proxy.example:65536", id="port-too-large"),
        pytest.param("http://proxy.example:-1", id="negative-port"),
        pytest.param("http://proxy.example/path", id="path"),
        pytest.param("http://proxy.example?x=1", id="query"),
        pytest.param("http://proxy.example#frag", id="fragment"),
        pytest.param("https://proxy.example", id="unsupported-https-proxy-endpoint"),
        pytest.param("socks5://proxy.example:1080", id="unsupported-scheme"),
    ],
)
def test_proxy_url_rejects_invalid_proxy_shapes(value: str) -> None:
    with pytest.raises(ValueError, match="proxy URL"):
        ProxyUrl.parse(value)
