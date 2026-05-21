from collections.abc import Mapping

from faker import Faker
import pytest

import foghttp
from foghttp.methods import GET
from foghttp.status_codes.success import OK


WINDOWS_1251_TEXT = "\u041f\u0440\u0438\u0432\u0435\u0442"
UTF_8_BOM_TEXT = "FogHTTP"
UTF_16_TEXT = "\u041f\u0440\u0438\u0432\u0435\u0442 FogHTTP"


@pytest.mark.parametrize(
    (
        "headers",
        "content",
        "expected_encoding",
        "expected_text",
    ),
    [
        pytest.param(
            {"content-type": "text/plain; charset=windows-1251"},
            WINDOWS_1251_TEXT.encode("windows-1251"),
            "windows-1251",
            WINDOWS_1251_TEXT,
            id="windows-1251",
        ),
        pytest.param(
            {"content-type": 'text/plain; charset="windows-1251"'},
            WINDOWS_1251_TEXT.encode("windows-1251"),
            "windows-1251",
            WINDOWS_1251_TEXT,
            id="quoted-windows-1251",
        ),
        pytest.param(
            {"content-type": "text/plain; CHARSET=WINDOWS-1251"},
            WINDOWS_1251_TEXT.encode("windows-1251"),
            "windows-1251",
            WINDOWS_1251_TEXT,
            id="uppercase-charset",
        ),
        pytest.param(
            {"content-type": "text/plain; charset=not-a-codec"},
            UTF_8_BOM_TEXT.encode(),
            "utf-8",
            UTF_8_BOM_TEXT,
            id="invalid-charset-falls-back-to-utf-8",
        ),
        pytest.param(
            {"content-type": "text/plain; charset=utf-8\r\nx-extra: value"},
            UTF_8_BOM_TEXT.encode(),
            "utf-8",
            UTF_8_BOM_TEXT,
            id="malformed-content-type-falls-back-to-utf-8",
        ),
        pytest.param(
            {},
            b"\xef\xbb\xbf" + UTF_8_BOM_TEXT.encode(),
            "utf-8-sig",
            UTF_8_BOM_TEXT,
            id="utf-8-bom",
        ),
        pytest.param(
            {"content-type": "text/plain; charset=not-a-codec"},
            UTF_16_TEXT.encode("utf-16"),
            "utf-16",
            UTF_16_TEXT,
            id="invalid-charset-falls-back-to-bom",
        ),
        pytest.param(
            {},
            UTF_8_BOM_TEXT.encode(),
            "utf-8",
            UTF_8_BOM_TEXT,
            id="default-utf-8",
        ),
    ],
)
def test_response_text_uses_declared_charset_or_safe_fallback(
    headers: Mapping[str, str],
    content: bytes,
    expected_encoding: str,
    expected_text: str,
    faker: Faker,
) -> None:
    response = _response(headers=headers, content=content, url=faker.url())

    assert response.encoding == expected_encoding
    assert response.text == expected_text


def _response(
    *,
    headers: Mapping[str, str],
    content: bytes,
    url: str,
) -> foghttp.Response:
    return foghttp.Response(
        status_code=OK,
        headers=foghttp.Headers(headers),
        content=content,
        url=url,
        request=foghttp.RequestInfo(
            method=GET,
            url=url,
            headers=foghttp.Headers(),
        ),
        http_version="HTTP/1.1",
        elapsed=0.0,
    )
