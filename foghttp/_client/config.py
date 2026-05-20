__all__ = ("ClientConfig",)

from dataclasses import dataclass

from ..headers import HeaderSource
from ..limits import Limits
from ..timeouts import Timeouts
from ..tls import TLSConfig
from ..types import HttpVersions, QueryParams
from ..url import URL
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
    request_defaults: RequestBuildDefaults

    @classmethod
    def from_options(
        cls,
        *,
        base_url: str | URL | None,
        headers: HeaderSource,
        params: QueryParams,
        limits: Limits | None,
        timeouts: Timeouts | None,
        http_versions: HttpVersions,
        follow_redirects: bool,
        max_redirects: int,
        cookies: bool,
        trust_env: bool,
        tls: TLSConfig | None,
        runtime_workers: int | None,
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
            request_defaults=(
                DEFAULT_REQUEST_BUILD_DEFAULTS
                if base_url is None and headers is None and params is None
                else RequestBuildDefaults.from_options(base_url=base_url, headers=headers, params=params)
            ),
        )
