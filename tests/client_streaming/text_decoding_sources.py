__all__ = ("AsyncClosableByteIterator", "ClosableByteIterator")


class ClosableByteIterator:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self.closed = False
        self._chunks = iter(chunks)

    def __iter__(self) -> "ClosableByteIterator":
        return self

    def __next__(self) -> bytes:
        return next(self._chunks)

    def close(self) -> None:
        self.closed = True


class AsyncClosableByteIterator:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self.closed = False
        self._chunks = iter(chunks)

    def __aiter__(self) -> "AsyncClosableByteIterator":
        return self

    async def __anext__(self) -> bytes:
        try:
            return next(self._chunks)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def aclose(self) -> None:
        self.closed = True
