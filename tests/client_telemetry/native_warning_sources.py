__all__ = (
    "ControlledIdleClose",
    "NativeWarningBatch",
    "NativeWarningRecord",
    "NativeWarningSink",
    "capture_promoted_warnings",
    "controlled_idle_close",
    "raise_ambient_failure",
)

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
import socketserver
import threading
from typing import TYPE_CHECKING, NoReturn, cast
from unittest.mock import patch
import warnings

import foghttp


if TYPE_CHECKING:
    from foghttp._foghttp import RawTelemetryEvent


_IDLE_CLOSE_TIMEOUT = 5.0


def raise_ambient_failure() -> NoReturn:
    raise LookupError


@dataclass(frozen=True, slots=True)
class ControlledIdleClose:
    url: str
    release: threading.Event


@contextmanager
def controlled_idle_close() -> Iterator[ControlledIdleClose]:
    release = threading.Event()

    class IdleHandler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            request = b""
            while b"\r\n\r\n" not in request:
                chunk = self.request.recv(4096)
                if not chunk:
                    return
                request += chunk
            self.request.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
            if not release.wait(timeout=_IDLE_CLOSE_TIMEOUT):
                message = "idle connection close was not released"
                raise AssertionError(message)

    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), IdleHandler) as server:
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            yield ControlledIdleClose(f"http://127.0.0.1:{server.server_address[1]}", release)
        finally:
            release.set()
            server.shutdown()
            thread.join(timeout=_IDLE_CLOSE_TIMEOUT)
            if thread.is_alive():
                message = "controlled idle server did not stop"
                raise AssertionError(message)


@dataclass(frozen=True, slots=True)
class NativeWarningRecord:
    event_type: str
    request_id: int | None = None
    mode: str | None = None
    method: str | None = None
    origin: str | None = None
    elapsed_ns: int | None = None
    redirect_hop: int | None = None
    outcome: str | None = None
    error_type: str | None = None


@dataclass(slots=True)
class NativeWarningBatch:
    records: list[NativeWarningRecord]
    drains: list[int | None] = field(default_factory=list)

    def drain_telemetry_events(
        self,
        request_id: int | None = None,
    ) -> tuple[list["RawTelemetryEvent"], int]:
        self.drains.append(request_id)
        selected = [record for record in self.records if request_id is None or record.request_id in {None, request_id}]
        self.records = [
            record for record in self.records if request_id is not None and record.request_id not in {None, request_id}
        ]
        return cast("list[RawTelemetryEvent]", selected), 0


@dataclass(slots=True)
class NativeWarningSink:
    events: list[foghttp.TelemetryEvent] = field(default_factory=list)
    failures: list[RuntimeError] = field(default_factory=list)

    def emit(self, event: foghttp.TelemetryEvent) -> None:
        self.events.append(event)
        if event.event_type is foghttp.TelemetryEventType.CONNECTION_CLOSED:
            error = RuntimeError(f"client sink failure {len(self.failures)}")
            self.failures.append(error)
            raise error


@contextmanager
def capture_promoted_warnings() -> Iterator[list[RuntimeWarning]]:
    captured: list[RuntimeWarning] = []
    original_warn = warnings.warn

    def capture(
        message: str | Warning,
        category: type[Warning] | None = None,
        stacklevel: int = 1,
        source: object | None = None,
    ) -> None:
        try:
            original_warn(message, category, stacklevel=stacklevel, source=source)
        except RuntimeWarning as error:
            captured.append(error)
            raise

    with patch.object(warnings, "warn", capture):
        yield captured
