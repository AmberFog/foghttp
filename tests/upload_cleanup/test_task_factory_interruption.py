import asyncio
import sys
from typing import TYPE_CHECKING, Any

import pytest

from foghttp._upload_body.cleanup_owner import CleanupOwner

from .constants import COMPLETION_WATCHDOG
from .sources import AsyncCloseGate


if TYPE_CHECKING:
    from collections.abc import Coroutine


@pytest.mark.parametrize(
    ("task_options", "wrap"),
    [
        pytest.param(None, False, id="refused"),
        pytest.param({}, False, id="scheduled"),
        *(
            [
                pytest.param({"eager_start": True}, False, id="eager"),
                pytest.param({"eager_start": True}, True, id="wrapped-eager"),
            ]
            if sys.version_info >= (3, 12)
            else []
        ),
    ],
)
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_task_factory_failure_preserves_cleanup_and_reports_control_flow(
    error_type: type[BaseException],
    task_options: dict[str, bool] | None,
    *,
    wrap: bool,
) -> None:
    owner = CleanupOwner(max_active=1, max_obligations=1)
    source = AsyncCloseGate()
    failure = error_type("task factory failed")
    attempted = asyncio.Event()
    reported: list[BaseException] = []
    scheduled: list[asyncio.Task[None]] = []

    def fail_start(
        loop: asyncio.AbstractEventLoop,
        coroutine: "Coroutine[Any, Any, None]",
        **kwargs: Any,
    ) -> asyncio.Task[None]:
        loop.set_task_factory(previous_factory)
        if task_options is not None:
            target = _wrapped_close(coroutine) if wrap else coroutine
            scheduled.append(asyncio.Task(target, loop=loop, **(kwargs | task_options)))
        attempted.set()
        raise failure

    loop = asyncio.get_running_loop()
    previous_factory = loop.get_task_factory()
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: reported.append(context["exception"]))
    try:
        loop.set_task_factory(fail_start)
        completion = owner.reserve(1).submit_async(source.aclose)
        async with asyncio.timeout(COMPLETION_WATCHDOG):
            await attempted.wait()
    finally:
        loop.set_task_factory(previous_factory)
        loop.set_exception_handler(previous_handler)

    try:
        expected = [] if isinstance(failure, Exception) else [failure]
        assert reported == expected
        assert owner.snapshot()["reserved"] == 1
        assert completion.done() is False
        if task_options is None:
            assert owner.snapshot()["stalled"] == 1
            assert source.calls == 0
        else:
            async with asyncio.timeout(COMPLETION_WATCHDOG):
                await source.entered.wait()
            assert owner.snapshot()["active"] == 1
            assert source.task is scheduled[0]
    finally:
        source.release.set()
        owner.retry()
        async with asyncio.timeout(COMPLETION_WATCHDOG):
            await asyncio.wrap_future(completion)
    assert source.calls == 1
    assert source.finished.is_set()
    assert owner.snapshot()["reserved"] == 0
    for task in scheduled:
        assert task.done()
        assert task.exception() is None


async def test_interrupted_task_inspection_preserves_the_actual_task_failure() -> None:
    owner = CleanupOwner(max_active=1, max_obligations=1)
    source = AsyncCloseGate()
    wrapper_failure = RuntimeError("task wrapper failed before invoking cleanup")
    interruption = GeneratorExit("task inspection interrupted")
    inspected = asyncio.Event()
    reported: list[BaseException] = []

    class InterruptedInspection(asyncio.Task[None]):
        def exception(self) -> BaseException | None:
            if not inspected.is_set():
                inspected.set()
                raise interruption
            return super().exception()

    def factory(
        loop: asyncio.AbstractEventLoop,
        coroutine: "Coroutine[Any, Any, None]",
        **kwargs: Any,
    ) -> asyncio.Task[None]:
        async def wrapper() -> None:
            coroutine.close()
            raise wrapper_failure

        return InterruptedInspection(wrapper(), loop=loop, **kwargs)

    loop = asyncio.get_running_loop()
    previous_factory = loop.get_task_factory()
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: reported.append(context["exception"]))
    try:
        loop.set_task_factory(factory)
        completion = owner.reserve(1).submit_async(source.aclose)
        async with asyncio.timeout(COMPLETION_WATCHDOG):
            await inspected.wait()
    finally:
        loop.set_task_factory(previous_factory)
        loop.set_exception_handler(previous_handler)

    assert reported == [interruption]
    assert completion.done() is False
    assert owner.snapshot()["reserved"] == 0
    assert completion.exception(timeout=COMPLETION_WATCHDOG) is wrapper_failure
    assert source.calls == 0


async def _wrapped_close(coroutine: "Coroutine[Any, Any, None]") -> None:
    await coroutine
