import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager, suppress
import socket
import traceback

import pytest

from tests.support.async_server import serve_tcp


WATCHDOG = 3
OWNER_CANCEL = "cancelled by the server owner"


def _assert_reported(error: BaseException, *expected: BaseException) -> None:
    rendered = "".join(traceback.format_exception(error))
    for failure in expected:
        assert f"{type(failure).__name__}: {failure}" in rendered


@asynccontextmanager
async def _peer(port: int) -> AsyncIterator[asyncio.StreamReader]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        yield reader
    finally:
        writer.close()
        with suppress(ConnectionResetError):
            await writer.wait_closed()


@pytest.mark.parametrize("handler_count", [1, 2], ids=["one-failed-handler", "two-failed-handlers"])
async def test_reports_scenario_error_and_all_finished_handler_errors(handler_count: int) -> None:
    scenario_error = ArithmeticError("scenario failed")
    cause = KeyError("handler input missing")
    failures = [LookupError("first handler failed"), ValueError("second handler failed")][:handler_count]
    remaining = iter(failures)

    async def handle(_reader: asyncio.StreamReader, _writer: asyncio.StreamWriter) -> None:
        raise next(remaining) from cause

    async def interrupt_scenario() -> None:
        async with serve_tcp(handle) as port:
            for _ in failures:
                async with _peer(port) as peer:
                    assert await peer.read() == b""
            raise scenario_error

    async with asyncio.timeout(WATCHDOG):
        with pytest.raises((ArithmeticError, ExceptionGroup)) as raised:
            await interrupt_scenario()

    assert failures[0].__cause__ is cause
    _assert_reported(raised.value, scenario_error, *failures, cause)


@pytest.mark.parametrize("cancel_owner", [False, True], ids=["scenario-failed", "cancelled-during-teardown"])
async def test_reports_accept_handler_and_scenario_failures(
    monkeypatch: pytest.MonkeyPatch,
    *,
    cancel_owner: bool,
) -> None:
    accept_error = OSError("accept failed")
    handler_error = ValueError("handler finalization failed")
    scenario_error = LookupError("scenario failed")
    started = asyncio.Event()
    finalizing = asyncio.Event()
    finish_cleanup = asyncio.Event()
    exiting_scenario = asyncio.Event()

    def fail_accept(_listener: socket.socket) -> tuple[socket.socket, object]:
        raise accept_error

    async def handle(_reader: asyncio.StreamReader, _writer: asyncio.StreamWriter) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            finalizing.set()
            await finish_cleanup.wait()
            raise handler_error

    async def scenario() -> None:
        async with AsyncExitStack() as clients, serve_tcp(handle) as port:
            await clients.enter_async_context(_peer(port))
            await started.wait()
            with monkeypatch.context() as patch, socket.socket() as second_peer:
                patch.setattr(socket.socket, "accept", fail_accept)
                second_peer.settimeout(0)
                with suppress(BlockingIOError, InterruptedError):
                    second_peer.connect(("127.0.0.1", port))
                await finalizing.wait()
            exiting_scenario.set()
            raise scenario_error

    async with asyncio.timeout(WATCHDOG):
        owner = asyncio.create_task(scenario())
        try:
            await exiting_scenario.wait()
            if cancel_owner:
                owner.cancel(OWNER_CANCEL)
            finish_cleanup.set()
            with pytest.raises(asyncio.CancelledError if cancel_owner else ExceptionGroup) as raised:
                await owner
        finally:
            finish_cleanup.set()
            if not owner.done():
                owner.cancel()
            await asyncio.gather(owner, return_exceptions=True)

    if cancel_owner:
        assert raised.value.args == (OWNER_CANCEL,)
    _assert_reported(raised.value, scenario_error, handler_error, accept_error)


async def test_handler_cancelled_externally_keeps_its_reason() -> None:
    started = asyncio.get_running_loop().create_future()
    reason = "cancelled by the handler owner"

    async def handle(_reader: asyncio.StreamReader, _writer: asyncio.StreamWriter) -> None:
        started.set_result(asyncio.current_task())
        await asyncio.Event().wait()

    async with asyncio.timeout(WATCHDOG), AsyncExitStack() as clients, AsyncExitStack() as servers:
        port = await servers.enter_async_context(serve_tcp(handle))
        peer = await clients.enter_async_context(_peer(port))
        handler = await started
        handler.cancel(reason)
        with pytest.raises(asyncio.CancelledError, match=reason):
            await servers.aclose()
        assert handler.cancelled()
        assert await peer.read() == b""


@pytest.mark.parametrize("during_teardown", [False, True], ids=["in-scenario", "in-teardown"])
@pytest.mark.parametrize("handler_fails", [False, True], ids=["clean-handler", "failing-handler"])
async def test_cancelled_owner_joins_handler_and_closes_peer(*, during_teardown: bool, handler_fails: bool) -> None:
    loop = asyncio.get_running_loop()
    bound = loop.create_future()
    started = loop.create_future()
    end_scenario = asyncio.Event()
    end_handler = asyncio.Event()
    finalizing = asyncio.Event()
    complete = asyncio.Event()
    cleanup_error = OSError("handler finalization failed")

    async def handle(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        started.set_result((asyncio.current_task(), writer.get_extra_info("socket")))
        try:
            await end_handler.wait()
        finally:
            finalizing.set()
            await complete.wait()
            if handler_fails:
                raise cleanup_error

    async def scenario() -> None:
        async with serve_tcp(handle) as port:
            bound.set_result(port)
            await end_scenario.wait()

    async with asyncio.timeout(WATCHDOG):
        owner = asyncio.create_task(scenario())
        try:
            async with _peer(await bound) as peer:
                handler, server_socket = await started
                if during_teardown:
                    end_scenario.set()
                    await finalizing.wait()
                owner.cancel(OWNER_CANCEL)
                await finalizing.wait()
                await asyncio.sleep(0)
                assert not owner.done()
                assert not handler.done()
                complete.set()
                await asyncio.wait((owner,))
                with pytest.raises(asyncio.CancelledError, match=OWNER_CANCEL) as raised:
                    await owner
                if handler_fails:
                    assert "OSError: handler finalization failed" in "".join(traceback.format_exception(raised.value))
                assert handler.done()
                assert server_socket.fileno() == -1
                assert await peer.read() == b""
        finally:
            end_handler.set()
            complete.set()
            end_scenario.set()
            await asyncio.gather(owner, return_exceptions=True)
