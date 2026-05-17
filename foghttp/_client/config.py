__all__ = ("ClientConfig",)

from dataclasses import dataclass

from ..limits import Limits
from ..timeouts import Timeouts
from ..tls import TLSConfig
from ..types import HttpVersions
from .options import validate_client_options
from .request_builder.defaults import DEFAULT_REQUEST_BUILD_DEFAULTS, RequestBuildDefaults


@dataclass(frozen=True, slots=True)
class ClientConfig:
    limits: Limits
    timeouts: Timeouts
    follow_redirects: bool
    max_redirects: int
    trust_env: bool
    tls: TLSConfig | None
    runtime_workers: int | None
    observability: bool
    request_defaults: RequestBuildDefaults

    @classmethod
    def from_options(
        cls,
        *,
        limits: Limits | None,
        timeouts: Timeouts | None,
        http_versions: HttpVersions,
        follow_redirects: bool,
        max_redirects: int,
        cookies: bool,
        trust_env: bool,
        tls: TLSConfig | None,
        runtime_workers: int | None,
        observability: bool,
    ) -> "ClientConfig":
        validate_client_options(
            cookies=cookies,
            max_redirects=max_redirects,
            runtime_workers=runtime_workers,
            trust_env=trust_env,
            http_versions=http_versions,
        )
        return cls(
            limits=limits or Limits(),
            timeouts=timeouts or Timeouts(),
            follow_redirects=follow_redirects,
            max_redirects=max_redirects,
            trust_env=trust_env,
            tls=tls,
            runtime_workers=runtime_workers,
            observability=observability,
            request_defaults=DEFAULT_REQUEST_BUILD_DEFAULTS,
        )
