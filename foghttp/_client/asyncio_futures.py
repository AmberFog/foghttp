__all__ = (
    "cancel_if_pending",
    "set_exception_if_pending",
    "set_result_if_pending",
)

from asyncio import Future


def cancel_if_pending(future: Future[object]) -> None:
    if future.done():
        return
    future.cancel()


def set_result_if_pending(future: Future[object], result: object) -> None:
    if future.done():
        return
    future.set_result(result)


def set_exception_if_pending(future: Future[object], exception: BaseException) -> None:
    if future.done():
        return
    future.set_exception(exception)
