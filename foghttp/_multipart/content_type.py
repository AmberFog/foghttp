from ..messages import (
    MULTIPART_CONTENT_TYPE_BOUNDARY_UNSUPPORTED,
    MULTIPART_CONTENT_TYPE_UNSUPPORTED,
)
from .constants import BOUNDARY_PARAMETER, MULTIPART_FORM_DATA
from .values import header_value


def explicit_content_type_with_boundary(content_type: str, boundary: str) -> str:
    media_type, parameters = _content_type_parts(content_type)
    if media_type.lower() != MULTIPART_FORM_DATA:
        raise ValueError(MULTIPART_CONTENT_TYPE_UNSUPPORTED)
    if any(_parameter_name(parameter) == BOUNDARY_PARAMETER for parameter in parameters):
        raise ValueError(MULTIPART_CONTENT_TYPE_BOUNDARY_UNSUPPORTED)
    return content_type_with_boundary(media_type, parameters, boundary)


def content_type_with_boundary(
    media_type: str,
    parameters: tuple[str, ...],
    boundary: str,
) -> str:
    return "; ".join((media_type, *parameters, f"{BOUNDARY_PARAMETER}={boundary}"))


def _content_type_parts(content_type: str) -> tuple[str, tuple[str, ...]]:
    header_value(content_type)
    parts = _stripped_parts(content_type)
    if not parts:
        raise ValueError(MULTIPART_CONTENT_TYPE_UNSUPPORTED)
    return parts[0], parts[1:]


def _stripped_parts(content_type: str) -> tuple[str, ...]:
    parts = []
    for part in _ContentTypeSplitter(content_type).split():
        stripped = part.strip()
        if stripped:
            parts.append(stripped)
    return tuple(parts)


class _ContentTypeSplitter:
    def __init__(self, content_type: str) -> None:
        self._content_type = content_type
        self._parts: list[str] = []
        self._buffer: list[str] = []
        self._in_quote = False
        self._escape = False

    def split(self) -> tuple[str, ...]:
        for char in self._content_type:
            self._append(char)
        self._finish()
        return tuple(self._parts)

    def _append(self, char: str) -> None:
        if self._escape:
            self._append_escaped(char)
            return
        if self._starts_escape(char):
            self._buffer.append(char)
            self._escape = True
            return
        if char == '"':
            self._in_quote = not self._in_quote
            self._buffer.append(char)
            return
        if char == ";" and not self._in_quote:
            self._push_part()
            return
        self._buffer.append(char)

    def _append_escaped(self, char: str) -> None:
        self._buffer.append(char)
        self._escape = False

    def _starts_escape(self, char: str) -> bool:
        return char == "\\" and self._in_quote

    def _push_part(self) -> None:
        self._parts.append("".join(self._buffer))
        self._buffer.clear()

    def _finish(self) -> None:
        if self._in_quote or self._escape:
            raise ValueError(MULTIPART_CONTENT_TYPE_UNSUPPORTED)
        self._push_part()


def _parameter_name(parameter: str) -> str:
    return parameter.partition("=")[0].strip().lower()
