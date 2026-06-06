__all__ = ("ClientConfig",)

from collections.abc import Mapping
from dataclasses import dataclass

from ..lifecycle_debug import AsyncLifecycleDebugConfig
from ..limits import Limits
from ..telemetry import TelemetryConfig
from ..timeouts import Timeouts
from ..tls import TLSConfig
from .options import ClientOptions, validate_client_options
from .proxy import ProxyResolver, environment_proxy_config, tls_from_trusted_environment
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
    proxy_resolver: ProxyResolver
    runtime_workers: int | None
    telemetry: TelemetryConfig | None
    lifecycle_debug: AsyncLifecycleDebugConfig | None
    request_defaults: RequestBuildDefaults

    @classmethod
    def from_options(
        cls,
        options: ClientOptions,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> "ClientConfig":
        validate_client_options(options)
        env_config = environment_proxy_config(environ) if options.trust_env else None
        return cls(
            limits=_DEFAULT_LIMITS if options.limits is None else options.limits,
            timeouts=_DEFAULT_TIMEOUTS if options.timeouts is None else options.timeouts,
            follow_redirects=options.follow_redirects,
            max_redirects=options.max_redirects,
            trust_env=options.trust_env,
            tls=tls_from_trusted_environment(explicit_tls=options.tls, env_config=env_config),
            proxy_resolver=(
                ProxyResolver.disabled() if env_config is None else ProxyResolver.from_environment(env_config.rules)
            ),
            runtime_workers=options.runtime_workers,
            telemetry=options.telemetry,
            lifecycle_debug=options.lifecycle_debug,
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
