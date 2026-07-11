__all__ = ("close_raw_client", "create_raw_client")

import foghttp._foghttp as _foghttp  # noqa: PLR0402

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
            ca_certificates=ca_certificate_bytes(config.tls),
            trust_webpki_roots=trust_webpki_roots(config.tls),
            runtime=config.runtime,
            runtime_workers=config.runtime_workers,
            http_proxy_url=None if config.http_proxy is None else config.http_proxy.endpoint_url,
            http_proxy_authorization=basic_proxy_authorization(config.http_proxy),
            https_proxy_url=None if config.https_proxy is None else config.https_proxy.endpoint_url,
            https_proxy_authorization=basic_proxy_authorization(config.https_proxy),
            policy_hooks=config.policy_hooks,
        )
    except _foghttp.FogHttpError as exc:
        raise ValueError(str(exc)) from exc
