from collections.abc import Mapping
from typing import assert_type

import foghttp
from foghttp.methods import GET


def test_request_extensions_have_a_typed_mapping_contract() -> None:
    source: Mapping[str, object] = {"tests.request_id": "request-1"}
    request = foghttp.Request(GET, "https://example.invalid", extensions=source)

    assert_type(request.extensions, foghttp.RequestExtensions)
    assert_type(request.extensions["tests.request_id"], object)
    assert request.extensions == source


def sync_shortcut_accepts_extensions(
    client: foghttp.Client,
    source: Mapping[str, object],
    url: str,
) -> None:
    assert_type(client.get(url, extensions=source), foghttp.Response)


async def async_shortcut_accepts_extensions(
    client: foghttp.AsyncClient,
    source: Mapping[str, object],
    url: str,
) -> None:
    assert_type(await client.get(url, extensions=source), foghttp.Response)
