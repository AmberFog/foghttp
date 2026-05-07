__all__ = (
    "HttpVersion",
    "HttpVersions",
)

from typing import Literal, TypeAlias


HttpVersion: TypeAlias = Literal["HTTP/1.1"]
HttpVersions: TypeAlias = list[HttpVersion] | None
