__all__ = ("HeaderPairs", "HeaderSource", "Headers")

from collections.abc import Iterable, Iterator, Mapping, MutableMapping
from typing import TypeAlias

from ._redaction import REDACTED_VALUE, redact_header_value


HeaderPairs: TypeAlias = list[tuple[str, str]]
HeaderMappingSource: TypeAlias = Mapping[str, str]
HeaderIterableSource: TypeAlias = Iterable[tuple[str, str]]
HeaderSource: TypeAlias = HeaderMappingSource | HeaderIterableSource | None


class Headers(MutableMapping[str, str]):
    """Case-insensitive HTTP headers with repeated value support."""

    def __init__(self, headers: HeaderSource = None) -> None:
        self._items: list[tuple[str, str, str]] = []
        self._mutation_serial = 0
        self._mutation_versions: dict[str, int] | None = None
        self._sensitive_names: frozenset[str] = frozenset()
        if headers is None:
            return
        if isinstance(headers, Headers):
            self._sensitive_names = headers._sensitive_names  # noqa: SLF001
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
        self._record_mutation(lower_name)

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
        return f"{self.__class__.__name__}({self._redacted_items()!r})"

    def add(self, name: str, value: str) -> None:
        lower_name = normalize_header_name(name)
        self._items.append((name, lower_name, value))
        self._record_mutation(lower_name)

    def set(self, name: str, value: str) -> None:
        lower_name = normalize_header_name(name)
        self._items = [item for item in self._items if item[1] != lower_name]
        self._items.append((name, lower_name, value))
        self._record_mutation(lower_name)

    def get_list(self, name: str) -> list[str]:
        lower_name = normalize_header_name(name)
        return [value for _original_name, item_name, value in self._items if item_name == lower_name]

    def multi_items(self) -> HeaderPairs:
        return [(name, value) for name, _lower_name, value in self._items]

    def copy(self) -> "Headers":
        return Headers(self)

    def _mark_sensitive(self, names: Iterable[str]) -> None:
        self._sensitive_names = self._sensitive_names | frozenset(normalize_header_name(name) for name in names)

    def _mutation_checkpoint(self) -> int:
        if self._mutation_versions is None:
            self._mutation_versions = {}
        return self._mutation_serial

    def _mutations_after(self, checkpoint: int) -> frozenset[str]:
        if self._mutation_versions is None:
            return frozenset()
        return frozenset(name for name, version in self._mutation_versions.items() if version > checkpoint)

    def _record_mutation(self, lower_name: str) -> None:
        if self._mutation_versions is None:
            return
        self._mutation_serial += 1
        self._mutation_versions[lower_name] = self._mutation_serial

    def _redacted_items(self) -> HeaderPairs:
        return [
            (
                name,
                REDACTED_VALUE if lower_name in self._sensitive_names else redact_header_value(name, value),
            )
            for name, lower_name, value in self._items
        ]


def normalize_header_name(name: str) -> str:
    return name.lower()
