__all__ = ("close_raw_client", "create_raw_client")

from dataclasses import dataclass

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from ...errors import NetworkError
from ...retry import RetryPolicy
from ...ssrf import SSRFPolicy
from ..config import ClientConfig
from ..proxy.auth import basic_proxy_authorization
from ..tls import ca_certificate_bytes, trust_webpki_roots


def close_raw_client(raw_client: _foghttp.RawClient) -> None:
    raw_client.close()


def create_raw_client(
    *,
    config: ClientConfig,
) -> _foghttp.RawClient:
    try:
        limits = config.limits
        retry_options = _RawRetryOptions.from_policy(config.retry)
        ssrf_options = _RawSSRFOptions.from_policy(config.ssrf)
        return _foghttp.RawClient(
            max_active_requests=limits.max_active_requests,
            max_active_requests_per_origin=limits.max_active_requests_per_origin,
            max_connections=limits.max_connections,
            max_connections_per_host=limits.max_connections_per_host,
            max_idle_connections_per_host=limits.max_idle_connections_per_host,
            max_pending_requests=limits.max_pending_requests,
            max_response_body_size=limits.max_response_body_size,
            max_buffered_response_bytes=limits.max_buffered_response_bytes,
            idle_timeout=limits.idle_timeout,
            keepalive=limits.keepalive,
            connect_timeout=config.timeouts.connect,
            follow_redirects=config.follow_redirects,
            max_redirects=config.max_redirects,
            cookies_enabled=config.cookies,
            ca_certificates=ca_certificate_bytes(config.tls),
            trust_webpki_roots=trust_webpki_roots(config.tls),
            runtime=config.runtime,
            runtime_workers=config.runtime_workers,
            http_proxy_url=None if config.http_proxy is None else config.http_proxy.endpoint_url,
            http_proxy_authorization=basic_proxy_authorization(config.http_proxy),
            https_proxy_url=None if config.https_proxy is None else config.https_proxy.endpoint_url,
            https_proxy_authorization=basic_proxy_authorization(config.https_proxy),
            auth_basic_authorization=(None if config.auth is None else config.auth.basic_authorization),
            auth_hook=None if config.auth is None else config.auth.hook,
            policy_hooks=config.policy_hooks,
            retry_retries=retry_options.retries,
            retry_backoff=retry_options.backoff,
            retry_jitter=retry_options.jitter,
            retry_statuses=retry_options.statuses,
            retry_methods=retry_options.methods,
            retry_network_errors=retry_options.network_errors,
            ssrf_allowed_schemes=ssrf_options.schemes,
            ssrf_allowed_origins=ssrf_options.origins,
            ssrf_allowed_domains=ssrf_options.domains,
        )
    except _foghttp.FogHttpError as exc:
        raise ValueError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class _RawRetryOptions:
    retries: int | None
    backoff: float
    jitter: float
    statuses: list[int]
    methods: list[str]
    network_errors: bool

    @classmethod
    def from_policy(cls, policy: RetryPolicy | None) -> "_RawRetryOptions":
        if policy is None:
            return cls(
                retries=None,
                backoff=0,
                jitter=0,
                statuses=[],
                methods=[],
                network_errors=False,
            )
        return cls(
            retries=policy.retries,
            backoff=policy.backoff,
            jitter=policy.jitter,
            statuses=sorted(policy.retry_on.statuses),
            methods=sorted(policy.methods),
            network_errors=NetworkError in policy.retry_on.exceptions,
        )


@dataclass(frozen=True, slots=True)
class _RawSSRFOptions:
    schemes: list[str] | None
    origins: list[str]
    domains: list[str]

    @classmethod
    def from_policy(cls, policy: SSRFPolicy | None) -> "_RawSSRFOptions":
        if policy is None:
            return cls(schemes=None, origins=[], domains=[])
        return cls(
            schemes=sorted(policy.allowed_schemes),
            origins=sorted(policy.allowed_origins),
            domains=sorted(policy.allowed_domains),
        )
