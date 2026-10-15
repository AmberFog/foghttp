from contextlib import suppress
import logging
import threading
from typing import TYPE_CHECKING, Literal

from ..url import URL
from .attributes import known_methods
from .configuration import configured_tracer
from .span import RequestSpan


if TYPE_CHECKING:
    import opentelemetry.trace

    from ..request import Request


_LOGGER = logging.getLogger("foghttp.opentelemetry")


class OpenTelemetryTracing:
    """Opt in to logical request spans using an application-owned provider.

    Does not activate spans, propagate headers, or configure/close an SDK.
    The optional API is imported only when constructing this integration.
    """

    def __init__(self, *, tracer_provider: "opentelemetry.trace.TracerProvider | None" = None) -> None:
        try:
            import opentelemetry.context  # noqa: PLC0415
            import opentelemetry.trace  # noqa: PLC0415
        except ModuleNotFoundError as error:
            if error.name not in {"opentelemetry", "opentelemetry.context", "opentelemetry.trace"}:
                raise
            msg = "OpenTelemetry tracing requires foghttp[opentelemetry]"
            raise ImportError(msg) from error
        self._known_methods = known_methods()
        self._context = opentelemetry.context
        self._trace = opentelemetry.trace
        self._diagnostic_lock = threading.Lock()
        self._failure_reported = False
        self._tracer = configured_tracer(tracer_provider)

    def _start(self, request: "Request", *, mode: Literal["buffered", "stream"]) -> RequestSpan | None:
        try:
            return self._start_span(request, mode=mode)
        except Exception:  # noqa: BLE001 - instrumentation must not fail the request
            self._report_failure()
            return None

    def _start_span(self, request: "Request", *, mode: Literal["buffered", "stream"]) -> RequestSpan:
        method = request.method if request.method in self._known_methods else "_OTHER"
        url = URL(request.url)
        span = self._tracer.start_span(
            request.method if request.method in self._known_methods else "HTTP",
            context=self._context.get_current(),
            kind=self._trace.SpanKind.CLIENT,
            attributes={
                "http.request.method": method,
                "server.address": url.host,
                "server.port": url.port,
                "url.scheme": url.scheme,
                "foghttp.request.mode": mode,
            },
            record_exception=False,
            set_status_on_exception=False,
        )
        return RequestSpan(span, self._report_failure)

    def _report_failure(self) -> None:
        with self._diagnostic_lock:
            if self._failure_reported:
                return
            self._failure_reported = True
        with suppress(Exception):
            _LOGGER.warning("FogHTTP OpenTelemetry instrumentation failed")
