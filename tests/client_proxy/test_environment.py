from faker import Faker
import pytest

from foghttp._client.proxy import (
    NoProxyMatcher,
    ProxyResolver,
    ProxyRules,
    ProxySource,
    ProxyTransportPolicy,
    ProxyUrl,
    environment_proxy_config,
)


def test_scheme_specific_proxy_wins_over_all_proxy() -> None:
    config = environment_proxy_config(
        {
            "HTTPS_PROXY": "http://scheme.proxy.example:8080",
            "ALL_PROXY": "http://all.proxy.example:8080",
        },
    )

    decision = ProxyResolver.from_environment(config.rules).resolve("https://api.example.com/items")

    assert decision.source is ProxySource.ENVIRONMENT
    assert decision.proxy is not None
    assert decision.proxy.endpoint_url == "http://scheme.proxy.example:8080"


def test_all_proxy_is_used_when_scheme_specific_proxy_is_absent() -> None:
    config = environment_proxy_config({"ALL_PROXY": "http://all.proxy.example:8080"})

    decision = ProxyResolver.from_environment(config.rules).resolve("https://api.example.com/items")

    assert decision.source is ProxySource.ENVIRONMENT
    assert decision.proxy is not None
    assert decision.proxy.endpoint_url == "http://all.proxy.example:8080"


def test_empty_environment_rules_do_not_enable_proxy_transport_policy() -> None:
    resolver = ProxyResolver.from_environment(environment_proxy_config({}).rules)

    assert resolver.transport_policy() is ProxyTransportPolicy.DIRECT


def test_environment_proxy_enables_environment_transport_policy() -> None:
    resolver = ProxyResolver.from_environment(
        environment_proxy_config({"ALL_PROXY": "http://all.proxy.example:8080"}).rules,
    )

    assert resolver.transport_policy() is ProxyTransportPolicy.ENVIRONMENT_PROXY


def test_explicit_proxy_enables_explicit_transport_policy_for_all_target_schemes() -> None:
    resolver = ProxyResolver.from_explicit(proxy=ProxyUrl.parse("http://proxy.example:8080"))

    http_decision = resolver.resolve("http://api.example.com/items")
    https_decision = resolver.resolve("https://api.example.com/items")

    assert resolver.transport_policy() is ProxyTransportPolicy.EXPLICIT_PROXY
    assert http_decision.proxy is https_decision.proxy


def test_lowercase_proxy_env_wins_over_uppercase_proxy_env() -> None:
    config = environment_proxy_config(
        {
            "https_proxy": "http://lower.proxy.example:8080",
            "HTTPS_PROXY": "http://upper.proxy.example:8080",
        },
    )

    decision = ProxyResolver.from_environment(config.rules).resolve("https://api.example.com/items")

    assert decision.proxy is not None
    assert decision.proxy.endpoint_url == "http://lower.proxy.example:8080"


def test_uppercase_http_proxy_is_ignored_in_cgi_environment() -> None:
    config = environment_proxy_config(
        {
            "HTTP_PROXY": "http://header.proxy.example:8080",
            "REQUEST_METHOD": "GET",
        },
    )

    decision = ProxyResolver.from_environment(config.rules).resolve("http://api.example.com/items")

    assert decision.source is ProxySource.NONE
    assert decision.proxy is None


def test_lowercase_http_proxy_is_allowed_in_cgi_environment() -> None:
    config = environment_proxy_config(
        {
            "http_proxy": "http://trusted.proxy.example:8080",
            "HTTP_PROXY": "http://header.proxy.example:8080",
            "REQUEST_METHOD": "GET",
        },
    )

    decision = ProxyResolver.from_environment(config.rules).resolve("http://api.example.com/items")

    assert decision.source is ProxySource.ENVIRONMENT
    assert decision.proxy is not None
    assert decision.proxy.endpoint_url == "http://trusted.proxy.example:8080"


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("HTTP_PROXY", id="http-proxy"),
        pytest.param("HTTPS_PROXY", id="https-proxy"),
    ],
)
def test_proxy_env_rejects_zero_port(name: str) -> None:
    with pytest.raises(ValueError, match=f"{name} is invalid") as exc_info:
        environment_proxy_config({name: "http://proxy.example:0"})

    assert "port must be between 1 and 65535" in str(exc_info.value)


def test_no_proxy_bypasses_environment_proxy() -> None:
    config = environment_proxy_config(
        {
            "HTTPS_PROXY": "http://proxy.example:8080",
            "NO_PROXY": "api.example.com",
        },
    )

    decision = ProxyResolver.from_environment(config.rules).resolve("https://api.example.com/items")

    assert decision.source is ProxySource.NO_PROXY
    assert decision.proxy is None
    assert decision.no_proxy_rule == "api.example.com"


def test_explicit_proxy_rules_win_over_environment_and_no_proxy() -> None:
    resolver = ProxyResolver(
        explicit=ProxyRules(https=ProxyUrl.parse("http://explicit.proxy.example:8080")),
        environment=ProxyRules(
            https=ProxyUrl.parse("http://env.proxy.example:8080"),
            no_proxy=NoProxyMatcher.parse("*"),
        ),
    )

    decision = resolver.resolve("https://api.example.com/items")

    assert decision.source is ProxySource.EXPLICIT
    assert decision.proxy is not None
    assert decision.proxy.endpoint_url == "http://explicit.proxy.example:8080"


def test_invalid_proxy_url_error_does_not_leak_credentials(faker: Faker) -> None:
    username = faker.user_name()
    hidden_value = faker.pystr(min_chars=12, max_chars=12)
    with pytest.raises(ValueError, match="HTTPS_PROXY is invalid") as exc_info:
        environment_proxy_config({"HTTPS_PROXY": f"socks5://{username}:{hidden_value}@proxy.example:1080"})

    message = str(exc_info.value)
    assert "HTTPS_PROXY is invalid" in message
    assert username not in message
    assert hidden_value not in message


def test_https_scheme_proxy_endpoint_is_rejected() -> None:
    with pytest.raises(ValueError, match="HTTPS_PROXY is invalid") as exc_info:
        environment_proxy_config({"HTTPS_PROXY": "https://proxy.example:443"})

    assert "scheme must be http" in str(exc_info.value)


def test_malformed_proxy_host_error_does_not_leak_credentials(faker: Faker) -> None:
    username = faker.user_name()
    hidden_value = faker.pystr(min_chars=12, max_chars=12)
    with pytest.raises(ValueError, match="HTTPS_PROXY is invalid") as exc_info:
        environment_proxy_config({"HTTPS_PROXY": f"http://{username}:{hidden_value}@[::1"})

    message = str(exc_info.value)
    assert "HTTPS_PROXY is invalid" in message
    assert username not in message
    assert hidden_value not in message
