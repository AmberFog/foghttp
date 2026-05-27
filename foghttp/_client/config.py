__all__ = ("ClientConfig",)

from dataclasses import dataclass

from ..limits import Limits
from ..timeouts import Timeouts
from ..tls import TLSConfig
from .options import ClientOptions, validate_client_options
from .request_builder.defaults import DEFAULT_REQUEST_BUILD_DEFAULTS, RequestBuildDefaults


_DEFAULT_LIMITS = Limits()
_DEFAULT_TIMEOUTS = Timeouts()


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
        options: ClientOptions,
    ) -> "ClientConfig":
        validate_client_options(options)
        return cls(
            limits=options.limits if options.limits is not None else _DEFAULT_LIMITS,
            timeouts=options.timeouts if options.timeouts is not None else _DEFAULT_TIMEOUTS,
            follow_redirects=options.follow_redirects,
            max_redirects=options.max_redirects,
            trust_env=options.trust_env,
            tls=options.tls,
            runtime_workers=options.runtime_workers,
            request_defaults=(
                DEFAULT_REQUEST_BUILD_DEFAULTS
                if options.base_url is None and options.headers is None and options.params is None
                else RequestBuildDefaults.from_options(
                    base_url=options.base_url,
                    headers=options.headers,
                    params=options.params,
                )
            ),
        )
