__all__ = ("raw_client_options",)


def raw_client_options(**overrides: object) -> dict[str, object]:
    options: dict[str, object] = {
        "max_active_requests": 1,
        "max_active_requests_per_origin": None,
        "max_connections": 1,
        "max_connections_per_host": None,
        "max_idle_connections_per_host": 1,
        "max_pending_requests": 1,
        "max_response_body_size": None,
        "max_buffered_response_bytes": None,
        "idle_timeout": 30.0,
        "keepalive": True,
        "connect_timeout": 2.0,
        "follow_redirects": False,
        "max_redirects": 20,
        "cookies_enabled": False,
        "ca_certificates": (),
        "trust_webpki_roots": True,
        "runtime": "dedicated",
        "runtime_workers": None,
        "http_proxy_url": None,
        "http_proxy_authorization": None,
        "https_proxy_url": None,
        "https_proxy_authorization": None,
        "auth_basic_authorization": None,
        "auth_hook": None,
        "policy_hooks": None,
        "retry_retries": None,
        "retry_backoff": 0.0,
        "retry_jitter": 0.0,
        "retry_statuses": (),
        "retry_methods": (),
        "retry_network_errors": False,
        "ssrf_allowed_schemes": None,
        "ssrf_allowed_origins": (),
        "ssrf_allowed_domains": (),
    }
    options.update(overrides)
    return options
