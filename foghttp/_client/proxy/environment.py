__all__ = (
    "EnvironmentProxyConfig",
    "environment_proxy_config",
    "tls_from_trusted_environment",
)

from collections.abc import Mapping
from dataclasses import dataclass
from os import environ

from ...tls import TLSConfig
from .constants import (
    ALL_PROXY_ENV_NAMES,
    HTTP_PROXY_ENV_NAMES,
    HTTPS_PROXY_ENV_NAMES,
    NO_PROXY_ENV_NAMES,
    REQUEST_METHOD_ENV_NAME,
    SSL_CERT_FILE_ENV_NAMES,
)
from .models import ProxyUrl
from .no_proxy import NoProxyMatcher
from .resolver import ProxyRules


@dataclass(frozen=True, slots=True)
class EnvironmentProxyConfig:
    rules: ProxyRules
    ssl_cert_file: str | None


def environment_proxy_config(env: Mapping[str, str] | None = None) -> EnvironmentProxyConfig:
    env_values = environ if env is None else env
    return EnvironmentProxyConfig(
        rules=ProxyRules(
            http=_proxy_url_from_env(env_values, _http_proxy_names(env_values)),
            https=_proxy_url_from_env(env_values, HTTPS_PROXY_ENV_NAMES),
            all_proxy=_proxy_url_from_env(env_values, ALL_PROXY_ENV_NAMES),
            no_proxy=NoProxyMatcher.parse(_env_value(env_values, NO_PROXY_ENV_NAMES)),
        ),
        ssl_cert_file=_env_value(env_values, SSL_CERT_FILE_ENV_NAMES),
    )


def tls_from_trusted_environment(
    *,
    explicit_tls: TLSConfig | None,
    env_config: EnvironmentProxyConfig | None,
) -> TLSConfig | None:
    if explicit_tls is not None or env_config is None or env_config.ssl_cert_file is None:
        return explicit_tls
    return TLSConfig(ca_certificates=(env_config.ssl_cert_file,))


def _http_proxy_names(env: Mapping[str, str]) -> tuple[str, ...]:
    if _env_value(env, (REQUEST_METHOD_ENV_NAME,)) is None:
        return HTTP_PROXY_ENV_NAMES
    return ("http_proxy",)


def _proxy_url_from_env(
    env: Mapping[str, str],
    names: tuple[str, ...],
) -> ProxyUrl | None:
    selected = _selected_env_value(env, names)
    if selected is None:
        return None
    name, value = selected
    try:
        return ProxyUrl.parse(value, source=name)
    except ValueError as error:
        msg = f"{name} is invalid: {error}"
        raise ValueError(msg) from error


def _env_value(env: Mapping[str, str], names: tuple[str, ...]) -> str | None:
    selected = _selected_env_value(env, names)
    if selected is None:
        return None
    _name, value = selected
    return value


def _selected_env_value(
    env: Mapping[str, str],
    names: tuple[str, ...],
) -> tuple[str, str] | None:
    for name in names:
        value = env.get(name)
        if value is not None and value.strip():
            return name, value.strip()
    return None
