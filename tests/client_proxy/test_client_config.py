from pathlib import Path

from faker import Faker
import pytest

import foghttp
from foghttp._client.config import ClientConfig
from foghttp._client.proxy import ProxySource
from foghttp.tls import TLSConfig

from .client_options import client_options
from .environment import clear_proxy_environment


def test_client_config_snapshots_trust_env_proxy_values() -> None:
    env = {"HTTPS_PROXY": "http://first.proxy.example:8080"}
    config = ClientConfig.from_options(client_options(trust_env=True), environ=env)

    env["HTTPS_PROXY"] = "http://second.proxy.example:8080"

    decision = config.proxy_resolver.resolve("https://api.example.com/items")
    assert decision.source is ProxySource.ENVIRONMENT
    assert decision.proxy is not None
    assert decision.proxy.endpoint_url == "http://first.proxy.example:8080"


def test_client_config_does_not_read_env_when_trust_env_is_disabled() -> None:
    config = ClientConfig.from_options(
        client_options(trust_env=False),
        environ={"HTTPS_PROXY": "not a proxy URL"},
    )

    decision = config.proxy_resolver.resolve("https://api.example.com/items")
    assert decision.source is ProxySource.NONE
    assert decision.proxy is None


def test_client_config_uses_explicit_http_proxy_over_environment() -> None:
    config = ClientConfig.from_options(
        client_options(trust_env=True, proxy="http://explicit.proxy.example:8080"),
        environ={
            "HTTP_PROXY": "http://environment.proxy.example:8080",
            "NO_PROXY": "*",
        },
    )

    decision = config.proxy_resolver.resolve("http://api.example.com/items")

    assert decision.source is ProxySource.EXPLICIT
    assert decision.proxy is not None
    assert decision.proxy.endpoint_url == "http://explicit.proxy.example:8080"
    assert config.http_proxy is decision.proxy


def test_client_config_redacts_proxy_credentials_in_repr(faker: Faker) -> None:
    username = faker.user_name()
    hidden_value = faker.pystr(min_chars=12, max_chars=12)
    config = ClientConfig.from_options(
        client_options(trust_env=True),
        environ={"HTTPS_PROXY": f"http://{username}:{hidden_value}@proxy.example:8080"},
    )

    representation = repr(config)
    decision = config.proxy_resolver.resolve("https://api.example.com/items")

    assert decision.proxy is not None
    assert decision.proxy.endpoint_url == "http://proxy.example:8080"
    assert decision.proxy.credentials is not None
    assert decision.proxy.redacted_url == "http://<redacted>@proxy.example:8080"
    assert username not in decision.proxy.endpoint_url
    assert hidden_value not in decision.proxy.endpoint_url
    assert username not in repr(decision.proxy)
    assert hidden_value not in repr(decision.proxy)
    assert username not in repr(decision.proxy.credentials)
    assert hidden_value not in repr(decision.proxy.credentials)
    assert "<redacted>@proxy.example:8080" in representation
    assert username not in representation
    assert hidden_value not in representation


def test_trust_env_ssl_cert_file_maps_to_tls_config(tmp_path: Path) -> None:
    ca_path = tmp_path / "ca.pem"
    ca_path.write_text("certificate")

    config = ClientConfig.from_options(
        client_options(trust_env=True),
        environ={"SSL_CERT_FILE": str(ca_path)},
    )

    assert config.tls == TLSConfig(ca_certificates=(str(ca_path),))


def test_trust_env_ssl_cert_file_validation_is_delayed(tmp_path: Path) -> None:
    ca_path = tmp_path / "missing-ca.pem"

    config = ClientConfig.from_options(
        client_options(trust_env=True),
        environ={"SSL_CERT_FILE": str(ca_path)},
    )

    assert config.tls == TLSConfig(ca_certificates=(str(ca_path),))


def test_trust_env_ignores_ssl_cert_dir(tmp_path: Path) -> None:
    config = ClientConfig.from_options(
        client_options(trust_env=True),
        environ={"SSL_CERT_DIR": str(tmp_path)},
    )

    assert config.tls is None


def test_explicit_tls_config_wins_over_ssl_cert_file(tmp_path: Path) -> None:
    env_ca_path = tmp_path / "env-ca.pem"
    explicit_ca_path = tmp_path / "explicit-ca.pem"
    explicit_tls = TLSConfig(ca_certificates=(explicit_ca_path,), trust_webpki_roots=False)

    config = ClientConfig.from_options(
        client_options(trust_env=True, tls=explicit_tls),
        environ={"SSL_CERT_FILE": str(env_ca_path)},
    )

    assert config.tls is explicit_tls


def test_public_client_accepts_trust_env_without_creating_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_proxy_environment(monkeypatch)

    with foghttp.Client(trust_env=True) as client:
        assert client.stats() == foghttp.TransportStats()


def test_public_client_rejects_invalid_trust_env_proxy_without_leaking_credentials(
    faker: Faker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    username = faker.user_name()
    hidden_value = faker.pystr(min_chars=12, max_chars=12)
    clear_proxy_environment(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", f"socks5://{username}:{hidden_value}@proxy.example:1080")

    with pytest.raises(ValueError, match="HTTPS_PROXY is invalid") as exc_info:
        foghttp.Client(trust_env=True)

    message = str(exc_info.value)
    assert username not in message
    assert hidden_value not in message


def test_public_client_ignores_invalid_proxy_env_when_trust_env_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_proxy_environment(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", "not a proxy URL")

    with foghttp.Client(trust_env=False) as client:
        assert client.stats() == foghttp.TransportStats()


async def test_public_async_client_accepts_trust_env_without_creating_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_proxy_environment(monkeypatch)

    async with foghttp.AsyncClient(trust_env=True) as client:
        assert client.stats() == foghttp.TransportStats()
