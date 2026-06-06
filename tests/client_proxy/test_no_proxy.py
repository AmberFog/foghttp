import pytest

from foghttp._client.proxy import NoProxyMatcher, ProxyTarget


@pytest.mark.parametrize(
    ("no_proxy", "url", "expected_rule"),
    [
        pytest.param("*", "https://api.example.com/items", "*", id="wildcard"),
        pytest.param("example.com", "https://example.com/items", "example.com", id="domain-apex"),
        pytest.param("example.com", "https://api.example.com/items", "example.com", id="domain-subdomain"),
        pytest.param(".example.com", "https://example.com/items", ".example.com", id="leading-dot-apex"),
        pytest.param(".example.com", "https://api.example.com/items", ".example.com", id="leading-dot-subdomain"),
        pytest.param("*.example.com", "https://example.com/items", "*.example.com", id="wildcard-dot-apex"),
        pytest.param("*.example.com", "https://api.example.com/items", "*.example.com", id="wildcard-dot-subdomain"),
        pytest.param("EXAMPLE.com", "https://api.example.com/items", "EXAMPLE.com", id="case-insensitive"),
        pytest.param("example.com:8443", "https://api.example.com:8443/items", "example.com:8443", id="port"),
        pytest.param("localhost", "http://localhost/items", "localhost", id="localhost"),
        pytest.param("127.0.0.1", "http://127.0.0.1/items", "127.0.0.1", id="ipv4"),
        pytest.param("[::1]", "http://[::1]/items", "[::1]", id="ipv6"),
        pytest.param("[::1]:8080", "http://[::1]:8080/items", "[::1]:8080", id="ipv6-port"),
        pytest.param(" *.example.org ", "https://api.example.org/items", "*.example.org", id="whitespace"),
    ],
)
def test_no_proxy_matcher_matches_supported_rules(
    no_proxy: str,
    url: str,
    expected_rule: str,
) -> None:
    target = ProxyTarget.parse(url)
    rule = NoProxyMatcher.parse(no_proxy).find_match(target)

    assert rule is not None
    assert rule.value == expected_rule


@pytest.mark.parametrize(
    ("no_proxy", "url"),
    [
        pytest.param("example.com:8443", "https://api.example.com/items", id="different-port"),
        pytest.param("example.com", "https://badexample.com/items", id="domain-boundary"),
        pytest.param(".example.com", "https://badexample.com/items", id="leading-dot-domain-boundary"),
        pytest.param("*.example.com", "https://badexample.com/items", id="wildcard-dot-domain-boundary"),
        pytest.param("localhost", "http://api.localhost/items", id="single-label-boundary"),
        pytest.param("127.0.0.1", "http://127.0.0.2/items", id="ipv4-exact"),
        pytest.param("[::1]:8080", "http://[::1]:9090/items", id="ipv6-different-port"),
    ],
)
def test_no_proxy_matcher_does_not_match_unrelated_targets(
    no_proxy: str,
    url: str,
) -> None:
    target = ProxyTarget.parse(url)

    assert NoProxyMatcher.parse(no_proxy).find_match(target) is None


@pytest.mark.parametrize(
    "no_proxy",
    [
        pytest.param("example.com:not-a-port", id="named-port"),
        pytest.param("[::1", id="unclosed-ipv6"),
        pytest.param("[::1]suffix", id="invalid-ipv6-suffix"),
        pytest.param("example.com:0", id="zero-port"),
        pytest.param("example.com:65536", id="port-too-large"),
        pytest.param("10.0.0.0/8", id="ipv4-cidr"),
        pytest.param("192.168.0.0/16:8080", id="ipv4-cidr-port"),
        pytest.param("2001:db8::/32", id="ipv6-cidr"),
        pytest.param(":8080", id="empty-host-with-port"),
        pytest.param(".", id="empty-dotted-host"),
        pytest.param("*.", id="empty-wildcard-suffix"),
        pytest.param("*..example.com", id="empty-wildcard-domain-label"),
        pytest.param("..example.com", id="empty-leading-domain-label"),
        pytest.param("example..com", id="empty-middle-domain-label"),
        pytest.param("exa*mple.com", id="stray-wildcard"),
        pytest.param("[]", id="empty-ipv6-host"),
        pytest.param("[]:8080", id="empty-ipv6-host-with-port"),
        pytest.param("[example.com]", id="bracketed-domain"),
        pytest.param("[localhost]", id="bracketed-localhost"),
        pytest.param("[not-an-ip]", id="bracketed-non-ip"),
        pytest.param("[127.0.0.1]", id="bracketed-ipv4"),
    ],
)
def test_no_proxy_matcher_rejects_malformed_rules(no_proxy: str) -> None:
    with pytest.raises(ValueError, match="NO_PROXY"):
        NoProxyMatcher.parse(no_proxy)


def test_no_proxy_matcher_ignores_empty_comma_tokens() -> None:
    matcher = NoProxyMatcher.parse("example.com,,localhost")

    assert tuple(rule.value for rule in matcher.rules) == ("example.com", "localhost")
