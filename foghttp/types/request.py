__all__ = (
    "QueryParamItem",
    "QueryParamItems",
    "QueryParamValue",
    "QueryParams",
)

from collections.abc import Mapping, Sequence
from typing import TypeAlias


_QueryParamScalar: TypeAlias = str | bytes | int | float | bool | None

QueryParamValue: TypeAlias = _QueryParamScalar | Sequence[_QueryParamScalar]
QueryParamItem: TypeAlias = tuple[str, QueryParamValue]
QueryParamItems: TypeAlias = Sequence[QueryParamItem]
QueryParams: TypeAlias = Mapping[str, QueryParamValue] | QueryParamItems | str | None
