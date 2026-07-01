from collections.abc import Mapping


def is_binary_file(content: object) -> bool:
    return callable(getattr(content, "read", None))


def is_async_stream(content: object) -> bool:
    return callable(getattr(content, "__aiter__", None))


def is_sync_stream(content: object) -> bool:
    if isinstance(content, bytearray | memoryview):
        return False
    if isinstance(content, Mapping):
        return False
    return callable(getattr(content, "__iter__", None))
