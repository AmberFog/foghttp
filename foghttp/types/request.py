__all__ = (
    "QueryParamValue",
    "QueryParams",
)

from collections.abc import Mapping, Sequence
from typing import TypeAlias


_QueryParamScalar: TypeAlias = str | bytes | int | float | bool | None

QueryParamValue: TypeAlias = _QueryParamScalar | Sequence[_QueryParamScalar]
QueryParams: TypeAlias = Mapping[str, QueryParamValue] | None
