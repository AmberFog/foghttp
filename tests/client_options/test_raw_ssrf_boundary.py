import pytest

from foghttp import _foghttp

from .raw_options import raw_client_options


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param(
            {"ssrf_allowed_schemes": ()},
            id="empty-schemes",
        ),
        pytest.param(
            {"ssrf_allowed_schemes": ("ftp",)},
            id="unsupported-scheme",
        ),
        pytest.param(
            {
                "ssrf_allowed_schemes": ("https",),
                "ssrf_allowed_origins": ("https://example.com/path",),
            },
            id="origin-with-path",
        ),
        pytest.param(
            {
                "ssrf_allowed_schemes": ("https",),
                "ssrf_allowed_origins": ("https://user:secret@example.com",),  # pragma: allowlist secret
            },
            id="origin-with-credentials",
        ),
        pytest.param(
            {
                "ssrf_allowed_schemes": ("https",),
                "ssrf_allowed_origins": ("https://example.com?",),
            },
            id="origin-with-empty-query",
        ),
        pytest.param(
            {
                "ssrf_allowed_schemes": ("https",),
                "ssrf_allowed_origins": ("https://example.com#",),
            },
            id="origin-with-empty-fragment",
        ),
        pytest.param(
            {
                "ssrf_allowed_schemes": ("https",),
                "ssrf_allowed_origins": ("https:example.com",),
            },
            id="origin-without-authority-delimiter",
        ),
        pytest.param(
            {
                "ssrf_allowed_schemes": ("https",),
                "ssrf_allowed_origins": ("https://example.com:",),
            },
            id="origin-with-empty-port",
        ),
        pytest.param(
            {
                "ssrf_allowed_schemes": ("https",),
                "ssrf_allowed_origins": ("https://example.com/a/..",),
            },
            id="origin-with-normalized-dot-path",
        ),
        pytest.param(
            {
                "ssrf_allowed_schemes": ("https",),
                "ssrf_allowed_origins": ("https://exam\nple.com",),
            },
            id="origin-with-embedded-control",
        ),
        pytest.param(
            {
                "ssrf_allowed_schemes": ("http",),
                "ssrf_allowed_origins": ("http://2130706433",),
            },
            id="origin-with-integer-ip",
        ),
        pytest.param(
            {
                "ssrf_allowed_schemes": ("http",),
                "ssrf_allowed_origins": ("http://0x7f000001",),
            },
            id="origin-with-hex-ip",
        ),
        pytest.param(
            {
                "ssrf_allowed_schemes": ("http",),
                "ssrf_allowed_origins": ("http://0177.0.0.1",),
            },
            id="origin-with-octal-ip",
        ),
        pytest.param(
            {
                "ssrf_allowed_schemes": ("http",),
                "ssrf_allowed_origins": ("http://127.1",),
            },
            id="origin-with-short-ip",
        ),
        pytest.param(
            {
                "ssrf_allowed_schemes": ("http",),
                "ssrf_allowed_origins": ("http://0x7f.1",),
            },
            id="origin-with-mixed-hex-ip",
        ),
        pytest.param(
            {
                "ssrf_allowed_schemes": ("https",),
                "ssrf_allowed_domains": ("127.0.0.1",),
            },
            id="domain-is-ip",
        ),
        pytest.param(
            {
                "ssrf_allowed_schemes": ("https",),
                "ssrf_allowed_domains": ("example%2ecom",),
            },
            id="domain-is-percent-encoded",
        ),
        pytest.param(
            {
                "ssrf_allowed_schemes": ("https",),
                "ssrf_allowed_domains": ("exam\nple.com",),
            },
            id="domain-with-embedded-control",
        ),
        pytest.param(
            {
                "ssrf_allowed_schemes": None,
                "ssrf_allowed_origins": ("https://example.com",),
            },
            id="payload-while-disabled",
        ),
    ],
)
def test_raw_client_rejects_invalid_ssrf_policy_without_panic(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(_foghttp.FogHttpError, match="SSRF"):
        _foghttp.RawClient(**raw_client_options(**overrides))


def test_raw_client_accepts_valid_ssrf_policy() -> None:
    client = _foghttp.RawClient(
        **raw_client_options(
            ssrf_allowed_schemes=("https",),
            ssrf_allowed_origins=("https://api.example.com",),
            ssrf_allowed_domains=("example.org",),
        ),
    )

    client.close()


def test_raw_client_accepts_unambiguous_ip_origins() -> None:
    client = _foghttp.RawClient(
        **raw_client_options(
            ssrf_allowed_schemes=("http", "https"),
            ssrf_allowed_origins=(
                "http://127.0.0.1:8080",
                "https://[2606:4700:4700::1111]",
            ),
        ),
    )

    client.close()
