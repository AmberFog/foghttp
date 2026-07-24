from dataclasses import FrozenInstanceError

from faker import Faker
import pytest

import foghttp
import foghttp._foghttp as native_foghttp
from foghttp.auth import AuthRequest
from foghttp.methods import GET
from tests.client_options.raw_options import raw_client_options


def test_auth_request_is_immutable_and_redacts_sensitive_state(faker: Faker) -> None:
    secret = faker.sha256()
    url = f"https://example.com/users?access_token={secret}"
    request = AuthRequest(
        method=GET,
        url=url,
        headers=(("Authorization", f"Bearer {secret}"),),
        redirect_hop=0,
        extensions=foghttp.RequestExtensions({"tests.request_id": "request-1"}),
    )

    with pytest.raises(FrozenInstanceError):
        request.url = "https://example.com/other"  # type: ignore[misc]

    representation = repr(request)
    assert secret not in representation
    assert "access_token=<redacted>" in representation
    assert "headers=<1 headers>" in representation
    assert request.headers == (("Authorization", f"Bearer {secret}"),)
    assert request.extensions == foghttp.RequestExtensions({"tests.request_id": "request-1"})


@pytest.mark.parametrize(
    ("auth", "message"),
    [
        (
            "username:password",
            r"auth must be a \(username, password\) tuple or a synchronous callable",
        ),
        (("username",), "auth basic credentials must contain exactly two strings"),
        (("username", object()), "auth basic credentials must contain exactly two strings"),
        (("user:name", "password"), "auth username must not contain ':'"),
    ],
)
def test_auth_rejects_invalid_configuration(auth: object, message: str) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        foghttp.Client(auth=auth)  # type: ignore[arg-type]


def test_auth_rejects_async_callable() -> None:
    async def authenticate(_request: AuthRequest) -> dict[str, str]:
        return {"Authorization": "Bearer token"}

    with pytest.raises(TypeError, match="auth hook must be synchronous"):
        foghttp.Client(auth=authenticate)  # type: ignore[arg-type]


def test_auth_rejects_async_callable_object() -> None:
    class AsyncAuth:
        async def __call__(self, _request: AuthRequest) -> None:
            return None

    with pytest.raises(TypeError, match="auth hook must be synchronous"):
        foghttp.Client(auth=AsyncAuth())


def test_raw_auth_boundary_rejects_conflicting_providers() -> None:
    with pytest.raises(
        ValueError,
        match="basic auth and callable auth cannot be enabled together",
    ):
        native_foghttp.RawClient(
            **raw_client_options(
                auth_basic_authorization="unused",
                auth_hook=lambda _request: None,
            ),
        )


def test_raw_auth_boundary_rejects_non_callable_hook() -> None:
    with pytest.raises(TypeError, match="auth hook must be callable"):
        native_foghttp.RawClient(**raw_client_options(auth_hook=object()))


def test_raw_auth_boundary_rejects_async_callable() -> None:
    async def authenticate(_request: AuthRequest) -> None:
        return None

    with pytest.raises(TypeError, match="auth hook must be synchronous"):
        native_foghttp.RawClient(**raw_client_options(auth_hook=authenticate))


def test_raw_auth_boundary_rejects_invalid_basic_header() -> None:
    with pytest.raises(ValueError, match="basic authorization header is invalid"):
        native_foghttp.RawClient(
            **raw_client_options(
                auth_basic_authorization="Basic ok\r\nInjected: yes",
            ),
        )


def test_client_configuration_repr_does_not_expose_basic_credentials(faker: Faker) -> None:
    username = faker.user_name()
    password = faker.password()
    client = foghttp.Client(auth=(username, password))

    try:
        representation = repr(client._config)  # noqa: SLF001
    finally:
        client.close()

    assert username not in representation
    assert password not in representation


def test_auth_provenance_repr_does_not_expose_header_values(faker: Faker) -> None:
    secret = faker.sha256()
    with foghttp.Client(
        headers={"Authorization": f"Bearer {secret}"},
        auth=("username", "password"),
    ) as client:
        request = client.build_request(GET, "https://example.com")

    provenance = request._auth_header_provenance  # noqa: SLF001
    assert provenance is not None
    assert secret not in repr(provenance)
