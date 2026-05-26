import pytest

import foghttp
from foghttp.url import merge_params


HTTPS_DEFAULT_PORT = 443
HTTP_ALT_PORT = 8080


def test_url_normalizes_scheme_host_and_default_port() -> None:
    url = foghttp.URL("HTTPS://Example.COM:443/path?q=1#fragment")

    assert str(url) == "https://example.com/path?q=1#fragment"
    assert url.scheme == "https"
    assert url.host == "example.com"
    assert url.port == HTTPS_DEFAULT_PORT
    assert url.path == "/path"
    assert url.query == "q=1"
    assert url.fragment == "fragment"
    assert url.origin == "https://example.com"


def test_url_origin_keeps_non_default_port() -> None:
    url = foghttp.URL("http://Example.COM:8080/path")

    assert str(url) == "http://example.com:8080/path"
    assert url.port == HTTP_ALT_PORT
    assert url.origin == "http://example.com:8080"


def test_url_preserves_explicit_zero_port() -> None:
    url = foghttp.URL("http://example.com:0/path")

    assert str(url) == "http://example.com:0/path"
    assert url.port == 0
    assert url.origin == "http://example.com:0"


def test_url_handles_ipv6_hosts() -> None:
    url = foghttp.URL("http://[::1]:80/path")

    assert str(url) == "http://[::1]/path"
    assert url.host == "::1"
    assert url.origin == "http://[::1]"


def test_url_preserves_userinfo_but_excludes_it_from_origin() -> None:
    url = foghttp.URL("https://user@Example.COM:443/path")

    assert str(url) == "https://user@example.com/path"
    assert url.origin == "https://example.com"


def test_url_repr_uses_normalized_url() -> None:
    url = foghttp.URL("https://Example.COM")

    assert repr(url) == "URL('https://example.com/')"


def test_url_compares_same_origin_with_default_ports() -> None:
    url = foghttp.URL("https://example.com")

    assert url.is_same_origin("https://example.com:443/path")
    assert not url.is_same_origin("http://example.com")
    assert not url.is_same_origin("https://api.example.com")
    assert not url.is_same_origin("https://example.com:444")


def test_url_joins_relative_locations() -> None:
    url = foghttp.URL("https://example.com/users/current/profile?debug=1")

    assert str(url.join("../settings?tab=security")) == "https://example.com/users/settings?tab=security"
    assert str(url.join("/login")) == "https://example.com/login"
    assert str(url.join("//api.example.com/v1")) == "https://api.example.com/v1"
    assert str(url.join("http://other.example/path")) == "http://other.example/path"


def test_url_uses_rust_canonicalization_for_empty_authority() -> None:
    url = foghttp.URL("https:///missing-host")

    assert str(url) == "https://missing-host/"
    assert url.host == "missing-host"


def test_url_normalizes_unicode_domains_to_idna() -> None:
    url = foghttp.URL("https://пример.рф/путь")

    assert str(url) == "https://xn--e1afmkfd.xn--p1ai/%D0%BF%D1%83%D1%82%D1%8C"
    assert url.host == "xn--e1afmkfd.xn--p1ai"
    assert url.origin == "https://xn--e1afmkfd.xn--p1ai"


def test_url_merge_params_preserves_existing_query_and_fragment() -> None:
    url = foghttp.URL("https://example.com/search?q=fog#results")

    assert str(url.with_params({"tag": ["rust", "python"]})) == (
        "https://example.com/search?q=fog&tag=rust&tag=python#results"
    )
    assert merge_params(url, {"page": 2}) == "https://example.com/search?q=fog&page=2#results"


@pytest.mark.parametrize(
    ("raw_url", "error_pattern"),
    [
        pytest.param("example.com/path", "URL is invalid", id="relative-url"),
        pytest.param("ftp://example.com", "URL scheme must be http or https", id="unsupported-scheme"),
        pytest.param("https://example.com:bad-port", "URL is invalid", id="bad-port"),
    ],
)
def test_url_rejects_invalid_urls(raw_url: str, error_pattern: str) -> None:
    with pytest.raises(ValueError, match=error_pattern):
        foghttp.URL(raw_url)


def test_url_rejects_invalid_idna_host() -> None:
    with pytest.raises(ValueError, match="URL is not valid Unicode"):
        foghttp.URL("https://\udcff.example")


def test_url_join_rejects_invalid_unicode_location() -> None:
    url = foghttp.URL("https://example.com")

    with pytest.raises(ValueError, match="URL is not valid Unicode"):
        url.join("https://\udcff.example")


def test_url_same_origin_rejects_invalid_unicode_location() -> None:
    url = foghttp.URL("https://example.com")

    with pytest.raises(ValueError, match="URL is not valid Unicode"):
        url.is_same_origin("https://\udcff.example")


def test_client_accepts_url_model(sync_http_server: str) -> None:
    with foghttp.Client() as client:
        response = client.get(foghttp.URL(sync_http_server + "/users"), params={"limit": 10})

    assert response.request.url == sync_http_server + "/users?limit=10"
    assert response.json()["request_line"] == "GET /users?limit=10 HTTP/1.1"
