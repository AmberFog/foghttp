__all__ = ("response_encoding",)

from codecs import BOM_UTF8, BOM_UTF16_BE, BOM_UTF16_LE, BOM_UTF32_BE, BOM_UTF32_LE, lookup
from email.message import Message
from email.policy import HTTP

from ..headers import Headers


DEFAULT_RESPONSE_ENCODING = "utf-8"
CONTENT_TYPE = "content-type"
BOM_ENCODINGS = (
    (BOM_UTF8, "utf-8-sig"),
    (BOM_UTF32_BE, "utf-32"),
    (BOM_UTF32_LE, "utf-32"),
    (BOM_UTF16_BE, "utf-16"),
    (BOM_UTF16_LE, "utf-16"),
)


def response_encoding(headers: Headers, content: bytes) -> str:
    if charset := _valid_content_type_charset(headers):
        return charset
    if encoding := _bom_encoding(content):
        return encoding
    return DEFAULT_RESPONSE_ENCODING


def _valid_content_type_charset(headers: Headers) -> str | None:
    content_type = headers.get(CONTENT_TYPE)
    if content_type is None:
        return None

    message = Message(policy=HTTP)
    try:
        message[CONTENT_TYPE] = content_type
    except ValueError:
        return None
    charset = message.get_content_charset()
    if charset is None:
        return None

    try:
        lookup(charset)
    except LookupError:
        return None
    return charset


def _bom_encoding(content: bytes) -> str | None:
    for bom, encoding in BOM_ENCODINGS:
        if content.startswith(bom):
            return encoding
    return None
