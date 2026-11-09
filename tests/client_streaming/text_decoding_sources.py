__all__ = ("AsyncClosableByteIterator", "ClosableByteIterator", "ResponseCloseRecorder")

from dataclasses import dataclass, field

import foghttp


@dataclass(slots=True)
class ResponseCloseRecorder:
    error: Exception | None = None
    calls: list[bool] = field(default_factory=list)
    closed: bool = False

    def __call__(self, *, suppress_telemetry_errors: bool) -> None:
        self.calls.append(suppress_telemetry_errors)
        if self.closed:
            return
        self.closed = True
        if self.error is not None:
            if suppress_telemetry_errors and isinstance(self.error, foghttp.TelemetryHookError):
                return
            raise self.error


class ClosableByteIterator:
    def __init__(
        self,
        chunks: tuple[bytes, ...],
        *,
        read_error: BaseException | None = None,
    ) -> None:
        self.closed = False
        self.read_count = 0
        self._chunks = iter(chunks)
        self._read_error = read_error

    def __iter__(self) -> "ClosableByteIterator":
        return self

    def __next__(self) -> bytes:
        self.read_count += 1
        if self._read_error is not None:
            raise self._read_error
        return next(self._chunks)

    def close(self) -> None:
        self.closed = True


class AsyncClosableByteIterator:
    def __init__(
        self,
        chunks: tuple[bytes, ...],
        *,
        read_error: BaseException | None = None,
    ) -> None:
        self.closed = False
        self.read_count = 0
        self._chunks = iter(chunks)
        self._read_error = read_error

    def __aiter__(self) -> "AsyncClosableByteIterator":
        return self

    async def __anext__(self) -> bytes:
        self.read_count += 1
        if self._read_error is not None:
            raise self._read_error
        try:
            return next(self._chunks)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def aclose(self) -> None:
        self.closed = True
