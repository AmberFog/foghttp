__all__ = ("ClientOptions", "validate_client_options")

from dataclasses import dataclass

from ..headers import HeaderSource
from ..lifecycle_debug import AsyncLifecycleDebugConfig
from ..limits import Limits
from ..messages import (
    COOKIES_UNSUPPORTED,
    HTTP_VERSION_UNSUPPORTED,
    MAX_REDIRECTS_INVALID,
)
from ..policy import RetryPolicy, SSRFPolicy, TransportPolicyHooks
from ..telemetry import TelemetryConfig
from ..timeouts import Timeouts
from ..tls import TLSConfig
from ..types import HttpVersions, QueryParams
from ..url import URL
from .runtime.validation import validate_runtime_options


@dataclass(frozen=True, slots=True)
class ClientOptions:
    base_url: str | URL | None
    headers: HeaderSource
    params: QueryParams
    limits: Limits | None
    timeouts: Timeouts | None
    http_versions: HttpVersions
    follow_redirects: bool
    max_redirects: int
    cookies: bool
    trust_env: bool
    proxy: str | URL | None
    tls: TLSConfig | None
    runtime: str | None
    runtime_workers: int | None
    policy_hooks: TransportPolicyHooks | None
    retry: RetryPolicy | None
    ssrf: SSRFPolicy | None
    telemetry: TelemetryConfig | None
    lifecycle_debug: AsyncLifecycleDebugConfig | None


def validate_client_options(options: ClientOptions) -> None:
    if options.max_redirects < 0:
        raise ValueError(MAX_REDIRECTS_INVALID)
    validate_runtime_options(
        runtime=options.runtime,
        runtime_workers=options.runtime_workers,
    )
    if options.cookies:
        raise NotImplementedError(COOKIES_UNSUPPORTED)
    if options.http_versions and options.http_versions != ["HTTP/1.1"]:
        raise NotImplementedError(HTTP_VERSION_UNSUPPORTED)
