__all__ = ("HistoryConversionProbe", "observe_history_conversion")

from collections.abc import Callable
from dataclasses import dataclass, field

import pytest

import foghttp
from foghttp import _foghttp as native
from foghttp._client import (
    response as response_mapping,
    transport,
)


HISTORY_CONVERSION_ERROR = "injected native history conversion failure"
HistoryConverter = Callable[..., foghttp.Response]
StreamConverter = Callable[..., foghttp.StreamResponse | foghttp.AsyncStreamResponse]


@dataclass(slots=True)
class HistoryConversionProbe:
    client: foghttp.Client | foghttp.AsyncClient
    history_converter: HistoryConverter
    stream_converter: StreamConverter
    failure_index: int | None = None
    raw_stream: native.RawStreamResponse | None = None
    history_items: list[native.RawResponse] = field(default_factory=list)
    reserved_before: list[int] = field(default_factory=list)

    def convert_history(
        self,
        *,
        raw: native.RawResponse,
        started: float,
        extensions: foghttp.RequestExtensions,
    ) -> foghttp.Response:
        stats = self.client.stats()
        self.reserved_before.append(stats.buffered_response_bytes)
        self.history_items.append(raw)
        if stats.active_requests != 1 or stats.buffered_response_bytes < len(raw.content):
            msg = "native history reservation was released before public bytes conversion"
            raise AssertionError(msg)
        if len(self.history_items) - 1 == self.failure_index:
            raise RuntimeError(HISTORY_CONVERSION_ERROR)
        return self.history_converter(raw=raw, started=started, extensions=extensions)

    def convert_stream(
        self,
        *,
        raw: native.RawStreamResponse,
        started: float,
        extensions: foghttp.RequestExtensions,
    ) -> foghttp.StreamResponse | foghttp.AsyncStreamResponse:
        self.raw_stream = raw
        return self.stream_converter(raw=raw, started=started, extensions=extensions)


def observe_history_conversion(
    monkeypatch: pytest.MonkeyPatch,
    client: foghttp.Client | foghttp.AsyncClient,
    *,
    failure_index: int | None = None,
) -> HistoryConversionProbe:
    name = "async_stream_response_from_raw" if isinstance(client, foghttp.AsyncClient) else "stream_response_from_raw"
    probe = HistoryConversionProbe(
        client,
        response_mapping.response_from_raw,
        getattr(transport, name),
        failure_index=failure_index,
    )
    monkeypatch.setattr(response_mapping, "response_from_raw", probe.convert_history)
    monkeypatch.setattr(transport, name, probe.convert_stream)
    return probe
