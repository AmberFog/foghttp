from json import JSONDecodeError
from typing import Any

import orjson
import pytest

import foghttp
from foghttp.methods import GET
from foghttp.status_codes.success import OK


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (b'"\xc3\xa9 \\u20ac \\ud83d\\ude80"', "\u00e9 \u20ac \U0001f680"),
        (b'"\\"\\\\\\b\\f\\n\\r\\t\\u0000"', '"\\\b\f\n\r\t\x00'),
        (
            b"[-7,1.25,1e-7,9007199254740993,18446744073709551615]",
            [-7, 1.25, 1e-7, 9007199254740993, 18446744073709551615],
        ),
        (b'{"items":[null,true,false,{},[]]}', {"items": [None, True, False, {}, []]}),
        (b"null", None),
        (b"false", False),
        (b"0", 0),
    ],
    ids=["unicode", "escapes", "numbers", "containers", "null", "boolean", "integer"],
)
def test_response_json_preserves_values(content: bytes, expected: Any) -> None:
    result = _response(content).json()

    assert result == expected
    assert type(result) is type(expected)


@pytest.mark.parametrize("content", [b"", b'{"x":}', b"{}{}", b'"\xff"', b'"\\ud800"', b"NaN", b"Infinity"])
def test_response_json_rejects_invalid_content_with_json_decode_error(content: bytes) -> None:
    response = _response(content)

    with pytest.raises(JSONDecodeError) as exc_info:
        response.json()

    assert isinstance(exc_info.value, orjson.JSONDecodeError)


def _response(content: bytes) -> foghttp.Response:
    url = "https://example.com/json"
    return foghttp.Response(
        status_code=OK,
        headers=foghttp.Headers({"content-type": "application/json"}),
        content=content,
        url=url,
        request=foghttp.RequestInfo(method=GET, url=url, headers=foghttp.Headers()),
        http_version="HTTP/1.1",
        elapsed=0.0,
    )
