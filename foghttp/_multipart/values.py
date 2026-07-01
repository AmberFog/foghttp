from pathlib import Path

from ..messages import MULTIPART_HEADER_VALUE_UNSUPPORTED, STREAMING_BODY_CHUNK_UNSUPPORTED


BACKSLASH = "\\"
QUOTE = '"'
_PRINTABLE_ASCII_START = 0x20
_DEL = 0x7F


def _is_header_value_char(char: str) -> bool:
    codepoint = ord(char)
    return _PRINTABLE_ASCII_START <= codepoint < _DEL


def body_chunk(content: object) -> bytes:
    if isinstance(content, bytes):
        return content
    if isinstance(content, bytearray):
        return bytes(content)
    if isinstance(content, memoryview):
        return content.tobytes()
    raise TypeError(STREAMING_BODY_CHUNK_UNSUPPORTED)


def header_value(value: str) -> str:
    if not all(_is_header_value_char(char) for char in value):
        raise ValueError(MULTIPART_HEADER_VALUE_UNSUPPORTED)
    return value


def text_value(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(MULTIPART_HEADER_VALUE_UNSUPPORTED)
    return header_value(value)


def filename_value(value: object) -> str:
    filename = text_value(value)
    if not filename:
        raise ValueError(MULTIPART_HEADER_VALUE_UNSUPPORTED)
    return filename


def filename_from_content(content: object, *, fallback: str) -> str:
    name = getattr(content, "name", None)
    if isinstance(name, str) and name:
        return filename_value(Path(name).name)
    return filename_value(fallback)


def quoted_header_value(value: str) -> str:
    safe_value = header_value(value)
    return safe_value.replace(BACKSLASH, BACKSLASH * 2).replace(QUOTE, BACKSLASH + QUOTE)
