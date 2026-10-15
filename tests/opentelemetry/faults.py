from collections import Counter
from collections.abc import Mapping
from typing import Any

from opentelemetry import trace


class InstrumentationInterrupt(BaseException):  # noqa: WPS418 - exercise non-Exception SDK control flow
    """Interrupt instrumentation without representing an ordinary SDK error."""


class FaultSpan(trace.NonRecordingSpan):
    def __init__(self, faults: dict[str, BaseException], *, recording: bool = True) -> None:
        super().__init__(trace.INVALID_SPAN_CONTEXT)
        self.faults = faults
        self.recording = recording
        self.calls: Counter[str] = Counter()
        self.attributes: dict[str, Any] = {}
        self.status = trace.StatusCode.UNSET
        self.description: str | None = None
        self.end_time: int | None = None

    def is_recording(self) -> bool:
        self._call("recording")
        return self.recording

    def set_attribute(self, key: str, value: Any) -> None:
        self._call("attribute")
        self.attributes[key] = value

    def set_attributes(self, attributes: Mapping[str, Any]) -> None:  # noqa: WPS615 - public Span API
        for key, value in attributes.items():
            self.set_attribute(key, value)

    def set_status(  # noqa: WPS615 - public Span API
        self,
        status: trace.Status | trace.StatusCode,
        description: str | None = None,
    ) -> None:
        self._call("status")
        self.status = status.status_code if isinstance(status, trace.Status) else status
        self.description = description

    def end(self, end_time: int | None = None) -> None:
        self.end_time = end_time
        self._call("end")

    def _call(self, stage: str) -> None:
        self.calls[stage] += 1
        failure = self.faults.get(stage)
        if failure is not None:
            raise failure


class FaultTracer(trace.NoOpTracer):
    def __init__(self, faults: dict[str, BaseException], *, recording: bool = True) -> None:
        self.faults = faults
        self.recording = recording
        self.spans: list[FaultSpan] = []
        self.start_attempts = 0

    def start_span(self, *_args: object, **_kwargs: object) -> FaultSpan:
        self.start_attempts += 1
        failure = self.faults.get("start")
        if failure is not None:
            raise failure
        span = FaultSpan(self.faults, recording=self.recording)
        self.spans.append(span)
        return span


class FaultProvider(trace.TracerProvider):
    def __init__(self, faults: dict[str, BaseException] | None = None, *, recording: bool = True) -> None:
        self.tracer = FaultTracer({} if faults is None else faults, recording=recording)

    def get_tracer(self, *_args: object, **_kwargs: object) -> trace.Tracer:  # noqa: WPS615 - public provider API
        return self.tracer
