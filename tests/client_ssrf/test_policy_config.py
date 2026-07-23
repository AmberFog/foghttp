from dataclasses import FrozenInstanceError

import pytest

import foghttp


def test_policy_normalizes_and_deduplicates_allowlists() -> None:
    policy = foghttp.SSRFPolicy(
        allowed_schemes=("HTTP", "https", "https"),
        allowed_origins=("https://EXAMPLE.com", foghttp.URL("https://example.com/")),
        allowed_domains=("EXAMPLE.org", "example.org"),
    )

    assert policy.allowed_schemes == frozenset({"http", "https"})
    assert policy.allowed_origins == frozenset({"https://example.com"})
    assert policy.allowed_domains == frozenset({"example.org"})


def test_policy_normalizes_unicode_domain_to_idna() -> None:
    policy = foghttp.SSRFPolicy(allowed_domains=("b\u00fccher.example",))

    assert policy.allowed_domains == frozenset({"xn--bcher-kva.example"})


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"allowed_schemes": "https"}, id="schemes-string"),
        pytest.param({"allowed_origins": "https://example.com"}, id="origins-string"),
        pytest.param({"allowed_domains": "example.com"}, id="domains-string"),
    ],
)
def test_policy_rejects_string_instead_of_collection(kwargs: dict[str, object]) -> None:
    with pytest.raises(TypeError, match="must be a collection"):
        foghttp.SSRFPolicy(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "schemes",
    [
        pytest.param((), id="empty"),
        pytest.param(("ftp",), id="unsupported"),
        pytest.param((" https",), id="whitespace"),
    ],
)
def test_policy_rejects_invalid_schemes(schemes: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="allowed_schemes"):
        foghttp.SSRFPolicy(allowed_schemes=schemes)


@pytest.mark.parametrize(
    "origin",
    [
        pytest.param("https://user:secret@example.com", id="credentials"),  # pragma: allowlist secret
        pytest.param("https://example.com/path", id="path"),
        pytest.param("https://example.com?token=secret", id="query"),
        pytest.param("https://example.com#fragment", id="fragment"),
        pytest.param("https://example.com?", id="empty-query"),
        pytest.param("https://example.com#", id="empty-fragment"),
        pytest.param("https:example.com", id="missing-authority-delimiter"),
        pytest.param("https://example.com:", id="empty-port"),
        pytest.param("https://example.com/a/..", id="normalized-dot-path"),
        pytest.param("https://exam\nple.com", id="embedded-control"),
        pytest.param("http://2130706433", id="integer-ip"),
        pytest.param("http://0x7f000001", id="hex-ip"),
        pytest.param("http://0177.0.0.1", id="octal-ip"),
        pytest.param("http://127.1", id="short-ip"),
        pytest.param("http://0x7f.1", id="mixed-hex-ip"),
        pytest.param("https://example%2ecom", id="percent-encoded-host"),
        pytest.param(r"https:\\example.com", id="backslash-authority"),
        pytest.param("https://@example.com", id="empty-userinfo"),
        pytest.param(" https://example.com", id="whitespace"),
    ],
)
def test_policy_rejects_invalid_origin_allowlist_values(origin: str) -> None:
    with pytest.raises(ValueError, match="origin-only"):
        foghttp.SSRFPolicy(allowed_origins=(origin,))


@pytest.mark.parametrize(
    "domain",
    [
        pytest.param("*.example.com", id="wildcard"),
        pytest.param(".example.com", id="leading-dot"),
        pytest.param("example.com.", id="trailing-dot"),
        pytest.param("example.com:443", id="port"),
        pytest.param("127.0.0.1", id="ip-address"),
        pytest.param("example%2ecom", id="percent-encoded-dot"),
        pytest.param("example..com", id="empty-label"),
        pytest.param("-example.com", id="leading-hyphen"),
        pytest.param("example-.com", id="trailing-hyphen"),
        pytest.param("exa_mple.com", id="underscore"),
        pytest.param("exam\nple.com", id="embedded-control"),
    ],
)
def test_policy_rejects_ambiguous_domain_allowlist_values(domain: str) -> None:
    with pytest.raises(ValueError, match="allowed_domains"):
        foghttp.SSRFPolicy(allowed_domains=(domain,))


def test_policy_rejects_origin_with_disabled_scheme() -> None:
    with pytest.raises(ValueError, match="allowed_schemes"):
        foghttp.SSRFPolicy(
            allowed_schemes=("https",),
            allowed_origins=("http://example.com",),
        )


def test_policy_accepts_unambiguous_ip_origin_syntax() -> None:
    policy = foghttp.SSRFPolicy(
        allowed_origins=("http://127.0.0.1:8080", "https://[2606:4700:4700::1111]"),
    )

    assert policy.allowed_origins == frozenset(
        {"http://127.0.0.1:8080", "https://[2606:4700:4700::1111]"},
    )


def test_policy_is_immutable() -> None:
    policy = foghttp.SSRFPolicy()

    with pytest.raises(FrozenInstanceError):
        policy.allowed_domains = frozenset({"example.com"})
