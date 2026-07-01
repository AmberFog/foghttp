from collections.abc import Mapping, Sequence
from typing import TypeAlias, cast

from ..messages import MULTIPART_DATA_UNSUPPORTED
from ..types import RequestData
from .models import MultipartField
from .values import text_value


DataItems: TypeAlias = Mapping[str, object] | Sequence[tuple[str, object]]


def multipart_fields(data: RequestData) -> tuple[MultipartField, ...]:
    if data is None:
        return ()
    if isinstance(data, bytes | str):
        raise TypeError(MULTIPART_DATA_UNSUPPORTED)
    try:
        return tuple(
            MultipartField(name=name, content=_field_content(value))
            for name, value in _iter_data_items(cast("DataItems", data))
        )
    except (TypeError, ValueError) as exc:
        raise TypeError(MULTIPART_DATA_UNSUPPORTED) from exc


def _iter_data_items(data: DataItems) -> list[tuple[str, object]]:
    items = data.items() if isinstance(data, Mapping) else data
    fields: list[tuple[str, object]] = []
    for raw_name, raw_value in items:
        name = text_value(raw_name)
        if _is_field_sequence(raw_value):
            fields.extend((name, value) for value in cast("Sequence[object]", raw_value))
        else:
            fields.append((name, raw_value))
    return fields


def _field_content(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    return str(value).encode("utf-8")


def _is_field_sequence(value: object) -> bool:
    if isinstance(value, str | bytes | bytearray | memoryview):
        return False
    return isinstance(value, Sequence)
