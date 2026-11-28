__all__ = (
    "DEFAULT_MAX_BUFFERED_RESPONSE_BYTES",
    "DEFAULT_MAX_RESPONSE_BODY_SIZE",
    "DEFAULT_MAX_STREAM_DECODER_MEMORY_BYTES",
    "DEFAULT_MAX_TOTAL_UPLOAD_BUFFER_BYTES",
    "DEFAULT_MAX_UPLOAD_BUFFER_BYTES",
    "Limits",
)

from dataclasses import dataclass

from ._validation.numeric import (
    validate_non_negative_int,
    validate_non_negative_seconds,
    validate_optional_non_negative_int,
    validate_positive_int,
)


DEFAULT_MAX_RESPONSE_BODY_SIZE = 10 * 1024 * 1024
DEFAULT_MAX_BUFFERED_RESPONSE_BYTES = 100 * 1024 * 1024
DEFAULT_MAX_STREAM_DECODER_MEMORY_BYTES = 134_217_728
DEFAULT_MAX_UPLOAD_BUFFER_BYTES = 524_288
DEFAULT_MAX_TOTAL_UPLOAD_BUFFER_BYTES = 16_777_216


@dataclass(frozen=True, slots=True)
class Limits:
    max_active_requests: int = 100
    max_active_requests_per_origin: int | None = None
    max_connections: int | None = None
    max_connections_per_host: int | None = None
    max_pending_requests: int = 1000
    max_response_body_size: int | None = DEFAULT_MAX_RESPONSE_BODY_SIZE
    max_buffered_response_bytes: int | None = DEFAULT_MAX_BUFFERED_RESPONSE_BYTES
    max_idle_connections_per_host: int = 20
    idle_timeout: float = 30.0
    keepalive: bool = True
    max_stream_decoded_bytes: int | None = None
    max_stream_decoder_memory_bytes: int = DEFAULT_MAX_STREAM_DECODER_MEMORY_BYTES
    max_upload_buffer_bytes: int = DEFAULT_MAX_UPLOAD_BUFFER_BYTES
    max_total_upload_buffer_bytes: int = DEFAULT_MAX_TOTAL_UPLOAD_BUFFER_BYTES

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_active_requests",
            validate_non_negative_int("Limits.max_active_requests", self.max_active_requests),
        )
        object.__setattr__(
            self,
            "max_active_requests_per_origin",
            validate_optional_non_negative_int(
                "Limits.max_active_requests_per_origin",
                self.max_active_requests_per_origin,
            ),
        )
        for name, limit in (
            ("max_connections", self.max_connections),
            ("max_connections_per_host", self.max_connections_per_host),
        ):
            object.__setattr__(self, name, validate_optional_non_negative_int(f"Limits.{name}", limit))
        object.__setattr__(
            self,
            "max_pending_requests",
            validate_non_negative_int("Limits.max_pending_requests", self.max_pending_requests),
        )
        for name, limit in (
            ("max_response_body_size", self.max_response_body_size),
            ("max_buffered_response_bytes", self.max_buffered_response_bytes),
            ("max_stream_decoded_bytes", self.max_stream_decoded_bytes),
        ):
            object.__setattr__(self, name, validate_optional_non_negative_int(f"Limits.{name}", limit))
        object.__setattr__(
            self,
            "max_idle_connections_per_host",
            validate_non_negative_int(
                "Limits.max_idle_connections_per_host",
                self.max_idle_connections_per_host,
            ),
        )
        object.__setattr__(
            self,
            "idle_timeout",
            validate_non_negative_seconds("Limits.idle_timeout", self.idle_timeout),
        )
        object.__setattr__(
            self,
            "max_stream_decoder_memory_bytes",
            validate_non_negative_int("Limits.max_stream_decoder_memory_bytes", self.max_stream_decoder_memory_bytes),
        )
        for name, limit in (
            ("max_upload_buffer_bytes", self.max_upload_buffer_bytes),
            ("max_total_upload_buffer_bytes", self.max_total_upload_buffer_bytes),
        ):
            object.__setattr__(self, name, validate_positive_int(f"Limits.{name}", limit))
