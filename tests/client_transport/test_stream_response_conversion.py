import asyncio

import pytest

from foghttp._client import response as response_mapping

from .stream_response_conversion_models import (
    StreamConverter,
    fail_conversion_at,
    stream_conversion_case,
)


@pytest.mark.parametrize(
    "converter",
    [response_mapping.stream_response_from_raw, response_mapping.async_stream_response_from_raw],
    ids=["sync", "async"],
)
@pytest.mark.parametrize(
    "phase",
    ["elapsed", "history_first", "history_middle", "headers", "request", "constructor", "retry_trace", "retry_bind"],
)
def test_stream_conversion_failure_releases_all_transferred_history(
    monkeypatch: pytest.MonkeyPatch,
    converter: StreamConverter,
    phase: str,
) -> None:
    raw, history = stream_conversion_case()
    error = RuntimeError(f"injected {phase} conversion failure")
    cause = ValueError("original failure cause")
    error.__cause__ = cause
    fail_conversion_at(monkeypatch, raw, phase=phase, error=error)

    with pytest.raises(RuntimeError) as exc_info:
        converter(raw=raw, started=0.0, extensions={})

    retained_error = exc_info.value
    assert retained_error is error
    assert retained_error.__cause__ is cause
    assert retained_error.__traceback__ is not None
    assert raw.close_count == 1
    assert raw.items == []
    assert raw.getter_count == 0
    assert all(not item.reserved and item.release_count == 1 for item in history)


@pytest.mark.parametrize(
    "converter",
    [response_mapping.stream_response_from_raw, response_mapping.async_stream_response_from_raw],
    ids=["sync", "async"],
)
def test_stream_conversion_handoff_failure_preserves_error_and_untransferred_history(
    monkeypatch: pytest.MonkeyPatch,
    converter: StreamConverter,
) -> None:
    raw, history = stream_conversion_case()
    error = RuntimeError("handoff rejected before transfer")
    fail_conversion_at(monkeypatch, raw, phase="take", error=error)

    with pytest.raises(RuntimeError) as exc_info:
        converter(raw=raw, started=0.0, extensions={})

    assert exc_info.value is error
    assert raw.close_count == 1
    assert raw.items == history[:3]
    assert all(item.reserved and item.release_count == 0 for item in history)


@pytest.mark.parametrize(
    "converter",
    [response_mapping.stream_response_from_raw, response_mapping.async_stream_response_from_raw],
    ids=["sync", "async"],
)
def test_stream_conversion_propagates_base_exception_after_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    converter: StreamConverter,
) -> None:
    raw, history = stream_conversion_case()
    error = asyncio.CancelledError("conversion interrupted")
    fail_conversion_at(monkeypatch, raw, phase="history_middle", error=error)

    with pytest.raises(asyncio.CancelledError) as exc_info:
        converter(raw=raw, started=0.0, extensions={})

    assert exc_info.value is error
    assert exc_info.value.__traceback__ is not None
    assert raw.close_count == 1
    assert all(not item.reserved and item.release_count == 1 for item in history)


@pytest.mark.parametrize(
    "converter",
    [response_mapping.stream_response_from_raw, response_mapping.async_stream_response_from_raw],
    ids=["sync", "async"],
)
def test_stream_conversion_releases_after_content_handoff_and_keeps_driver_open(
    converter: StreamConverter,
) -> None:
    raw, history = stream_conversion_case()

    response = converter(raw=raw, started=0.0, extensions={})

    assert [item.content for item in response.history] == [b"first", b"middle", b"last"]
    assert response.history[0].history[0].content == b"nested"
    assert response._raw is raw  # noqa: SLF001
    assert raw.items == []
    assert raw.close_count == 0
    assert raw.getter_count == 0
    for item in history:
        assert item.release_count == 1
        assert raw.events.index(("content", item.name)) < raw.events.index(("release", item.name))


@pytest.mark.parametrize(
    "converter",
    [response_mapping.stream_response_from_raw, response_mapping.async_stream_response_from_raw],
    ids=["sync", "async"],
)
def test_successful_stream_conversion_inside_exception_handler_keeps_driver_open(
    converter: StreamConverter,
) -> None:
    raw, history = stream_conversion_case()

    try:
        msg = "ambient exception"
        raise RuntimeError(msg)  # noqa: TRY301
    except RuntimeError:
        response = converter(raw=raw, started=0.0, extensions={})

    assert response._raw is raw  # noqa: SLF001
    assert raw.close_count == 0
    assert raw.items == []
    assert all(not item.reserved and item.release_count == 1 for item in history)
