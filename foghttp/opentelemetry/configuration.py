from importlib.metadata import version
from typing import TYPE_CHECKING

from ..errors import ConfigurationError


if TYPE_CHECKING:
    import opentelemetry.trace


_SCHEMA_URL = "https://opentelemetry.io/schemas/1.44.0"


def configured_tracer(provider: object) -> "opentelemetry.trace.Tracer":
    import opentelemetry.trace  # noqa: PLC0415

    if provider is not None and not isinstance(provider, opentelemetry.trace.TracerProvider):
        msg = "tracer_provider must be an OpenTelemetry TracerProvider"
        raise ConfigurationError(msg)
    try:
        return opentelemetry.trace.get_tracer(
            "foghttp",
            version("foghttp"),
            tracer_provider=provider,
            schema_url=_SCHEMA_URL,
        )
    except Exception as error:
        msg = "Could not obtain the OpenTelemetry tracer"
        raise ConfigurationError(msg) from error
