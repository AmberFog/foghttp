__all__ = ("close_raw_client", "create_raw_client")

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from ..config import ClientConfig
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
            limits.max_active_requests,
            limits.max_active_requests_per_origin,
            limits.max_idle_connections_per_host,
            limits.max_pending_requests,
            limits.max_response_body_size,
            limits.max_buffered_response_bytes,
            limits.idle_timeout,
            limits.keepalive,
            config.timeouts.connect,
            config.follow_redirects,
            config.max_redirects,
            ca_certificate_bytes(config.tls),
            trust_webpki_roots(config.tls),
            config.runtime_workers,
        )
    except _foghttp.FogHttpError as exc:
        raise ValueError(str(exc)) from exc
