__all__ = ("RequestExtensions", "RequestExtensionsSource")

from collections.abc import Iterator, Mapping
from types import MappingProxyType
from typing import TypeAlias, cast, overload


RequestExtensionsSource: TypeAlias = Mapping[str, object] | None

_RESERVED_NAMESPACE = "foghttp."


class RequestExtensions(Mapping[str, object]):
    """Immutable, request-scoped metadata passed outside the HTTP message."""

    __slots__ = ("_values",)

    @overload
    def __init__(self, extensions: None = None) -> None: ...

    @overload
    def __init__(self, extensions: Mapping[str, object]) -> None: ...

    def __init__(self, extensions: object = None) -> None:
        if extensions is not None and not isinstance(extensions, Mapping):
            message = "extensions must be a mapping or None"
            raise TypeError(message)

        source = {} if extensions is None else extensions
        raw_values: dict[object, object] = dict(source)
        _validate_extension_keys(raw_values)
        values = cast("dict[str, object]", raw_values)
        self._values: Mapping[str, object] = MappingProxyType(values)

    def __getitem__(self, key: str) -> object:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        item_count = len(self)
        return f"{class_name}(<{item_count} items>)"


def _validate_extension_keys(extensions: Mapping[object, object]) -> None:
    for key in extensions:
        if not isinstance(key, str):
            message = "request extension keys must be strings"
            raise TypeError(message)
        if not key:
            message = "request extension keys must not be empty"
            raise ValueError(message)
        if key.casefold().startswith(_RESERVED_NAMESPACE):
            message = "request extension keys cannot use the reserved 'foghttp.' namespace"
            raise ValueError(message)


_EMPTY_REQUEST_EXTENSIONS = RequestExtensions()


def empty_request_extensions() -> RequestExtensions:
    return _EMPTY_REQUEST_EXTENSIONS


def normalize_request_extensions(extensions: RequestExtensionsSource) -> RequestExtensions:
    if extensions is None:
        return _EMPTY_REQUEST_EXTENSIONS
    if isinstance(extensions, RequestExtensions):
        return extensions or _EMPTY_REQUEST_EXTENSIONS
    normalized = RequestExtensions(extensions)
    return normalized or _EMPTY_REQUEST_EXTENSIONS
