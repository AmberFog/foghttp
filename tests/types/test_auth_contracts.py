from typing import assert_type

import foghttp
from foghttp.methods import GET


def authenticate(request: foghttp.AuthRequest) -> dict[str, str]:
    assert_type(request.method, str)
    assert_type(request.url, str)
    assert_type(request.headers, tuple[tuple[str, str], ...])
    assert_type(request.redirect_hop, int)
    assert_type(request.extensions, foghttp.RequestExtensions)
    return {"Authorization": "Bearer token"}


async def test_auth_client_and_request_contracts() -> None:
    hook: foghttp.AuthHook = authenticate
    auth: foghttp.Auth = hook
    basic_auth: foghttp.Auth = ("username", "password")
    sync_client = foghttp.Client(auth=auth)
    async_client = foghttp.AsyncClient(auth=basic_auth)

    try:
        assert_type(hook, foghttp.AuthHook)
        assert_type(auth, foghttp.Auth)
        assert_type(basic_auth, foghttp.Auth)
        request = foghttp.AuthRequest(GET, "https://example.invalid", (), 0)
        assert_type(request, foghttp.AuthRequest)
        assert_type(sync_client, foghttp.Client)
        assert_type(async_client, foghttp.AsyncClient)
    finally:
        sync_client.close()
        await async_client.aclose()
