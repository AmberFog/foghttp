__all__ = ("client_options",)

from foghttp._client.constants import DEFAULT_MAX_REDIRECTS
from foghttp._client.options import ClientOptions
from foghttp.tls import TLSConfig


def client_options(
    *,
    trust_env: bool,
    tls: TLSConfig | None = None,
) -> ClientOptions:
    return ClientOptions(
        base_url=None,
        headers=None,
        params=None,
        limits=None,
        timeouts=None,
        http_versions=None,
        follow_redirects=False,
        max_redirects=DEFAULT_MAX_REDIRECTS,
        cookies=False,
        trust_env=trust_env,
        tls=tls,
        runtime_workers=None,
        telemetry=None,
        lifecycle_debug=None,
    )
