from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from foghttp._client import response as response_mapping
from foghttp.stream_response import AsyncStreamResponse, StreamResponse


StreamConverter = Callable[..., StreamResponse | AsyncStreamResponse]


@dataclass(slots=True)
class BufferedHistoryItem:
    name: str
    events: list[tuple[str, str]]
    children: list["BufferedHistoryItem"] = field(default_factory=list)
    reserved: bool = True
    release_count: int = 0
    status_code: int = 302
    headers: list[tuple[str, str]] = field(default_factory=lambda: [("X-History", "redirect")])
    url: str = "https://example.test/redirect"
    http_version: str = "HTTP/1.1"
    elapsed: float = 0.125
    retry_trace: None = None

    @property
    def request(self) -> SimpleNamespace:
        return SimpleNamespace(method="GET", url=self.url, headers=[], sensitive_headers=[])

    @property
    def history(self) -> list["BufferedHistoryItem"]:
        return self.children

    @property
    def content(self) -> bytes:
        self.events.append(("content", self.name))
        return self.name.encode()

    def release_buffered_body_reservations(self) -> None:
        if self.reserved:
            self.reserved = False
            self.release_count += 1
            self.events.append(("release", self.name))
        for child in self.children:
            child.release_buffered_body_reservations()


@dataclass(slots=True)
class ConversionStream:
    items: list[BufferedHistoryItem]
    events: list[tuple[str, str]]
    take_error: BaseException | None = None
    elapsed_error: BaseException | None = None
    close_count: int = 0
    getter_count: int = 0
    status_code: int = 200
    headers: list[tuple[str, str]] = field(default_factory=lambda: [("X-Final", "stream")])
    request: SimpleNamespace = field(
        default_factory=lambda: SimpleNamespace(
            method="GET",
            url="https://example.test/final",
            headers=[],
            sensitive_headers=[],
        ),
    )
    url: str = "https://example.test/final"
    http_version: str = "HTTP/1.1"
    retry_trace: None = None

    @property
    def elapsed(self) -> float:
        if self.elapsed_error is not None:
            raise self.elapsed_error
        return 0.5

    @property
    def history(self) -> list[BufferedHistoryItem]:
        self.getter_count += 1
        return list(self.items)

    def take_history(self) -> list[BufferedHistoryItem]:
        if self.take_error is not None:
            raise self.take_error
        result = self.items
        self.items = []
        self.events.append(("take", "stream"))
        return result

    def close(self) -> None:
        self.close_count += 1
        self.events.append(("close", "stream"))

    def release_buffered_body_reservations(self) -> None:
        for item in self.items:
            item.release_buffered_body_reservations()


def stream_conversion_case() -> tuple[ConversionStream, list[BufferedHistoryItem]]:
    events: list[tuple[str, str]] = []
    nested = BufferedHistoryItem("nested", events)
    items = [
        BufferedHistoryItem("first", events, children=[nested]),
        BufferedHistoryItem("middle", events),
        BufferedHistoryItem("last", events),
    ]
    return ConversionStream(items, events), [*items, nested]


def fail_conversion_at(
    monkeypatch: pytest.MonkeyPatch,
    raw: ConversionStream,
    *,
    phase: str,
    error: BaseException,
) -> None:
    if phase == "take":
        raw.take_error = error
    elif phase == "elapsed":
        raw.elapsed_error = error
    elif phase.startswith("history_"):
        original = response_mapping.response_from_raw
        selected = raw.items[0 if phase == "history_first" else 1]

        def convert_history(**kwargs: object) -> object:
            if kwargs["raw"] is selected:
                raise error
            return original(**kwargs)

        monkeypatch.setattr(response_mapping, "response_from_raw", convert_history)
    else:
        _fail_final_conversion(monkeypatch, raw, phase=phase, error=error)


def _fail_final_conversion(
    monkeypatch: pytest.MonkeyPatch,
    raw: ConversionStream,
    *,
    phase: str,
    error: BaseException,
) -> None:
    targets = {
        "headers": ("Headers", raw.headers),
        "request": ("request_info_from_raw", raw.request),
        "retry_trace": ("retry_trace_from_raw", raw),
    }
    conversion = targets.get(phase)
    if conversion is not None:
        name, selected = conversion
        original = getattr(response_mapping, name)

        def convert_final(value: object, **kwargs: object) -> object:
            if value is selected:
                raise error
            return original(value, **kwargs)

        monkeypatch.setattr(response_mapping, name, convert_final)
    elif phase == "constructor":

        def construct(**_kwargs: object) -> object:
            raise error

        monkeypatch.setattr(response_mapping, "StreamResponse", construct)
        monkeypatch.setattr(response_mapping, "AsyncStreamResponse", construct)
    else:
        original_bind = response_mapping.bind_retry_trace

        def bind(target: object, trace: object) -> object:
            if isinstance(target, (StreamResponse, AsyncStreamResponse)):
                raise error
            return original_bind(target, trace)

        monkeypatch.setattr(response_mapping, "bind_retry_trace", bind)
