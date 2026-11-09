import asyncio
import traceback

import pytest

import foghttp
from foghttp._streaming.text.async_chunks import aiter_text_chunks
from foghttp._streaming.text.lines import aiter_lines, iter_lines
from foghttp._streaming.text.sync_chunks import iter_text_chunks
from tests.client_streaming.text_decoding_sources import (
    AsyncClosableByteIterator,
    ClosableByteIterator,
    ResponseCloseRecorder,
)


def test_sync_text_cleanup_preserves_primary_identity_and_closes_byte_source() -> None:
    primary = RuntimeError("byte iteration failed")
    hook_error = foghttp.TelemetryHookError("completion hook failed")
    source = ClosableByteIterator((), read_error=primary)
    close_response = ResponseCloseRecorder(hook_error)
    iterator = iter_text_chunks(source, encoding="utf-8", errors="strict", close=close_response)

    with pytest.raises(RuntimeError, match="byte iteration failed") as error:
        next(iterator)

    assert error.value is primary
    assert any(frame.name == "__next__" for frame in traceback.extract_tb(error.value.__traceback__))
    assert source.closed
    assert close_response.calls == [True]


async def test_async_text_cleanup_preserves_primary_identity_and_closes_byte_source() -> None:
    primary = RuntimeError("byte iteration failed")
    hook_error = foghttp.TelemetryHookError("completion hook failed")
    source = AsyncClosableByteIterator((), read_error=primary)
    close_response = ResponseCloseRecorder(hook_error)
    iterator = aiter_text_chunks(source, encoding="utf-8", errors="strict", close=close_response)

    with pytest.raises(RuntimeError, match="byte iteration failed") as error:
        await anext(iterator)

    assert error.value is primary
    assert any(frame.name == "__anext__" for frame in traceback.extract_tb(error.value.__traceback__))
    assert source.closed
    assert close_response.calls == [True]


def test_sync_lines_cleanup_preserves_limit_error_and_closes_nested_byte_source() -> None:
    source = ClosableByteIterator((b"alpha", b"unread"))
    close_response = ResponseCloseRecorder(foghttp.TelemetryHookError())
    text = iter_text_chunks(source, encoding="utf-8", errors="strict", close=close_response)
    iterator = iter_lines(text, max_line_chars=4, close=close_response)

    with pytest.raises(foghttp.ResponseError, match="max_line_chars=4"):
        next(iterator)

    assert source.closed
    assert source.read_count == 1


async def test_async_lines_cleanup_preserves_limit_error_and_closes_nested_byte_source() -> None:
    source = AsyncClosableByteIterator((b"alpha", b"unread"))
    close_response = ResponseCloseRecorder(foghttp.TelemetryHookError())
    text = aiter_text_chunks(source, encoding="utf-8", errors="strict", close=close_response)
    iterator = aiter_lines(text, max_line_chars=4, close=close_response)

    with pytest.raises(foghttp.ResponseError, match="max_line_chars=4"):
        await anext(iterator)

    assert source.closed
    assert source.read_count == 1


@pytest.mark.parametrize("encoding", ["foghttp-unknown-codec", "base64_codec"])
def test_sync_setup_error_survives_close_hook_without_reading_source(encoding: str) -> None:
    source = ClosableByteIterator((b"unread",))
    iterator = iter_text_chunks(
        source,
        encoding=encoding,
        errors="strict",
        close=ResponseCloseRecorder(foghttp.TelemetryHookError()),
    )
    assert source.read_count == 0
    assert not source.closed

    with pytest.raises(LookupError):
        next(iterator)

    assert source.closed
    assert source.read_count == 0


@pytest.mark.parametrize("encoding", ["foghttp-unknown-codec", "base64_codec"])
async def test_async_setup_error_survives_close_hook_without_reading_source(encoding: str) -> None:
    source = AsyncClosableByteIterator((b"unread",))
    iterator = aiter_text_chunks(
        source,
        encoding=encoding,
        errors="strict",
        close=ResponseCloseRecorder(foghttp.TelemetryHookError()),
    )
    assert source.read_count == 0
    assert not source.closed

    with pytest.raises(LookupError):
        await anext(iterator)

    assert source.closed
    assert source.read_count == 0


def test_sync_success_cleanup_hook_error_still_closes_byte_source() -> None:
    source = ClosableByteIterator((b"alpha",))
    iterator = iter_text_chunks(
        source,
        encoding="utf-8",
        errors="strict",
        close=ResponseCloseRecorder(foghttp.TelemetryHookError()),
    )

    with pytest.raises(foghttp.TelemetryHookError):
        list(iterator)

    assert source.closed


async def test_async_success_cleanup_hook_error_still_closes_byte_source() -> None:
    source = AsyncClosableByteIterator((b"alpha",))
    iterator = aiter_text_chunks(
        source,
        encoding="utf-8",
        errors="strict",
        close=ResponseCloseRecorder(foghttp.TelemetryHookError()),
    )

    with pytest.raises(foghttp.TelemetryHookError):
        _ = [chunk async for chunk in iterator]

    assert source.closed


@pytest.mark.parametrize("lines", [False, True], ids=["text", "lines"])
def test_sync_explicit_iterator_close_keeps_hook_error_and_closes_source(*, lines: bool) -> None:
    source = ClosableByteIterator((b"alpha\n", b"unread"))
    close_response = ResponseCloseRecorder(foghttp.TelemetryHookError())
    text = iter_text_chunks(source, encoding="utf-8", errors="strict", close=close_response)
    iterator = iter_lines(text, close=close_response) if lines else text
    assert next(iterator).startswith("alpha")

    with pytest.raises(foghttp.TelemetryHookError):
        iterator.close()

    assert source.closed
    assert source.read_count == 1


@pytest.mark.parametrize("lines", [False, True], ids=["text", "lines"])
async def test_async_explicit_iterator_close_keeps_hook_error_and_closes_source(*, lines: bool) -> None:
    source = AsyncClosableByteIterator((b"alpha\n", b"unread"))
    close_response = ResponseCloseRecorder(foghttp.TelemetryHookError())
    text = aiter_text_chunks(source, encoding="utf-8", errors="strict", close=close_response)
    iterator = aiter_lines(text, close=close_response) if lines else text
    assert (await anext(iterator)).startswith("alpha")

    with pytest.raises(foghttp.TelemetryHookError):
        await iterator.aclose()

    assert source.closed
    assert source.read_count == 1


async def test_async_text_cleanup_preserves_cancellation_identity() -> None:
    primary = asyncio.CancelledError("cancelled byte iteration")
    source = AsyncClosableByteIterator((), read_error=primary)
    iterator = aiter_text_chunks(
        source,
        encoding="utf-8",
        errors="strict",
        close=ResponseCloseRecorder(foghttp.TelemetryHookError()),
    )

    with pytest.raises(asyncio.CancelledError) as error:
        await anext(iterator)

    assert error.value is primary
    assert source.closed


def test_sync_primary_error_does_not_hide_non_hook_cleanup_error() -> None:
    source = ClosableByteIterator((b"\xff",))
    iterator = iter_text_chunks(
        source,
        encoding="utf-8",
        errors="strict",
        close=ResponseCloseRecorder(RuntimeError("cleanup bug")),
    )

    with pytest.raises(RuntimeError, match="cleanup bug"):
        next(iterator)

    assert source.closed


async def test_async_primary_error_does_not_hide_non_hook_cleanup_error() -> None:
    source = AsyncClosableByteIterator((b"\xff",))
    iterator = aiter_text_chunks(
        source,
        encoding="utf-8",
        errors="strict",
        close=ResponseCloseRecorder(RuntimeError("cleanup bug")),
    )

    with pytest.raises(RuntimeError, match="cleanup bug"):
        await anext(iterator)

    assert source.closed


@pytest.mark.parametrize("close_early", [False, True], ids=["success", "iterator-close"])
@pytest.mark.parametrize("lines", [False, True], ids=["text", "lines"])
def test_sync_ambient_exception_handler_does_not_suppress_completion_hook(
    *,
    close_early: bool,
    lines: bool,
) -> None:
    source = ClosableByteIterator((b"alpha\n",))
    close_response = ResponseCloseRecorder(foghttp.TelemetryHookError())
    text = iter_text_chunks(source, encoding="utf-8", errors="strict", close=close_response)
    iterator = iter_lines(text, close=close_response) if lines else text
    if close_early:
        assert next(iterator).startswith("alpha")

    handled_source = ClosableByteIterator((), read_error=RuntimeError("unrelated handled failure"))
    try:
        next(handled_source)
    except RuntimeError:
        if close_early:
            with pytest.raises(foghttp.TelemetryHookError):
                iterator.close()
        else:
            with pytest.raises(foghttp.TelemetryHookError):
                list(iterator)

    assert source.closed


@pytest.mark.parametrize("close_early", [False, True], ids=["success", "iterator-close"])
@pytest.mark.parametrize("lines", [False, True], ids=["text", "lines"])
async def test_async_ambient_exception_handler_does_not_suppress_completion_hook(
    *,
    close_early: bool,
    lines: bool,
) -> None:
    source = AsyncClosableByteIterator((b"alpha\n",))
    close_response = ResponseCloseRecorder(foghttp.TelemetryHookError())
    text = aiter_text_chunks(source, encoding="utf-8", errors="strict", close=close_response)
    iterator = aiter_lines(text, close=close_response) if lines else text
    if close_early:
        assert (await anext(iterator)).startswith("alpha")

    handled_source = AsyncClosableByteIterator((), read_error=RuntimeError("unrelated handled failure"))
    try:
        await anext(handled_source)
    except RuntimeError:
        if close_early:
            with pytest.raises(foghttp.TelemetryHookError):
                await iterator.aclose()
        else:
            with pytest.raises(foghttp.TelemetryHookError):
                _ = [chunk async for chunk in iterator]

    assert source.closed
