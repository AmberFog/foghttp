__all__ = (
    "QueryParamItem",
    "QueryParamItems",
    "QueryParamValue",
    "QueryParams",
    "RequestData",
    "RequestDataItem",
    "RequestDataItems",
    "RequestDataValue",
)

from collections.abc import Mapping, Sequence
from typing import TypeAlias


_QueryParamScalar: TypeAlias = str | bytes | int | float | bool | None
_RequestDataScalar: TypeAlias = str | bytes | int | float | bool | None

QueryParamValue: TypeAlias = _QueryParamScalar | Sequence[_QueryParamScalar]
QueryParamItem: TypeAlias = tuple[str, QueryParamValue]
QueryParamItems: TypeAlias = Sequence[QueryParamItem]
QueryParams: TypeAlias = Mapping[str, QueryParamValue] | QueryParamItems | str | None

RequestDataValue: TypeAlias = _RequestDataScalar | Sequence[_RequestDataScalar]
RequestDataItem: TypeAlias = tuple[str, RequestDataValue]
RequestDataItems: TypeAlias = Sequence[RequestDataItem]
RequestData: TypeAlias = Mapping[str, RequestDataValue] | RequestDataItems | bytes | str | None
