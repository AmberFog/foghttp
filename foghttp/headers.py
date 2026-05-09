__all__ = ("HeaderPairs", "HeaderSource", "Headers")

from collections.abc import Iterable, Iterator, Mapping, MutableMapping
from typing import TypeAlias


HeaderPairs: TypeAlias = list[tuple[str, str]]
HeaderSource: TypeAlias = Mapping[str, str] | Iterable[tuple[str, str]] | None


class Headers(MutableMapping[str, str]):
    """Case-insensitive HTTP headers with repeated value support."""

    def __init__(self, headers: HeaderSource = None) -> None:
        self._items: list[tuple[str, str, str]] = []
        if headers is None:
            return
        source = headers.multi_items() if isinstance(headers, Headers) else headers
        source = source.items() if isinstance(source, Mapping) else source
        for name, value in source:
            self.add(name, value)

    def __getitem__(self, name: str) -> str:
        lower_name = normalize_header_name(name)
        for _original_name, item_name, value in reversed(self._items):
            if item_name == lower_name:
                return value
        raise KeyError(name)

    def __setitem__(self, name: str, value: str) -> None:
        self.set(name, value)

    def __delitem__(self, name: str) -> None:
        lower_name = normalize_header_name(name)
        original_len = len(self._items)
        self._items = [item for item in self._items if item[1] != lower_name]
        if len(self._items) == original_len:
            raise KeyError(name)

    def __iter__(self) -> Iterator[str]:
        seen: set[str] = set()
        for original_name, lower_name, _value in self._items:
            if lower_name in seen:
                continue
            seen.add(lower_name)
            yield original_name

    def __len__(self) -> int:
        return len({lower_name for _original_name, lower_name, _value in self._items})

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.multi_items()!r})"

    def add(self, name: str, value: str) -> None:
        self._items.append((name, normalize_header_name(name), value))

    def set(self, name: str, value: str) -> None:
        lower_name = normalize_header_name(name)
        self._items = [item for item in self._items if item[1] != lower_name]
        self._items.append((name, lower_name, value))

    def get_list(self, name: str) -> list[str]:
        lower_name = normalize_header_name(name)
        return [value for _original_name, item_name, value in self._items if item_name == lower_name]

    def multi_items(self) -> HeaderPairs:
        return [(name, value) for name, _lower_name, value in self._items]

    def copy(self) -> "Headers":
        return Headers(self.multi_items())


def normalize_header_name(name: str) -> str:
    return name.lower()
