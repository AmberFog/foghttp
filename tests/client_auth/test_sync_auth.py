from base64 import b64encode
from typing import cast

from faker import Faker
import pytest

import foghttp
from foghttp.auth import AuthRequest
from foghttp.headers import HeaderSource
from foghttp.methods import GET
from foghttp.status_codes.redirect import FOUND
from foghttp.telemetry import TelemetryConfig
from tests.client_telemetry.models import RecordingTelemetrySink
from tests.redirect_helpers import SECURITY_HEADERS_PATH, header_values, redirect_to_location_url


AUTH_REFRESH_FAILURE = "auth refresh failed"
ORIGIN_ROUND_TRIP_REDIRECTS = 2


@pytest.mark.parametrize("streaming", [False, True], ids=("buffered", "streaming"))
def test_sync_basic_auth_is_applied_for_each_transport_mode(
    sync_http_server: str,
    faker: Faker,
    *,
    streaming: bool,
) -> None:
    username = faker.user_name()
    password = faker.password()
    expected = _basic_authorization(username, password)
    url = f"{sync_http_server}{SECURITY_HEADERS_PATH}"
    with foghttp.Client(auth=(username, password)) as client:
        if streaming:
            with client.stream(GET, url) as response:
                assert response.request.headers["authorization"] == expected
        else:
            response = client.get(url)
            assert response.request.headers["authorization"] == expected


def test_sync_auth_header_merge_order_and_post_build_override(
    sync_http_server: str,
) -> None:
    url = f"{sync_http_server}{SECURITY_HEADERS_PATH}"
    with foghttp.Client(
        headers={"Authorization": "Bearer client-default"},
        auth=("username", "password"),
    ) as client:
        auth_response = client.get(url)
        per_request_response = client.get(url, headers={"Authorization": "Bearer per-request"})
        prepared = client.build_request(GET, url)
        prepared.headers["Authorization"] = "Bearer prepared-override"
        prepared_response = client.send(prepared)
        deleted = client.build_request(GET, url)
        del deleted.headers["Authorization"]
        deleted_response = client.send(deleted)
        direct_response = client.send(
            foghttp.Request(GET, url, headers={"Authorization": "Bearer direct"}),
        )

    assert header_values(auth_response.json(), "authorization") == [
        _basic_authorization("username", "password"),
    ]
    assert header_values(per_request_response.json(), "authorization") == ["Bearer per-request"]
    assert header_values(prepared_response.json(), "authorization") == ["Bearer prepared-override"]
    assert header_values(deleted_response.json(), "authorization") == []
    assert header_values(direct_response.json(), "authorization") == ["Bearer direct"]


def test_sync_prepared_header_mutations_remain_authoritative(
    sync_http_server: str,
) -> None:
    client_default = "Bearer client-default"

    def authenticate(_request: AuthRequest) -> dict[str, str]:
        return {
            "Authorization": "Bearer auth",
            "X-Auth-Proof": "auth-proof",
        }

    url = f"{sync_http_server}{SECURITY_HEADERS_PATH}"
    with foghttp.Client(
        headers={"Authorization": client_default},
        auth=authenticate,
    ) as client:
        same_value = client.build_request(GET, url)
        same_value.headers["Authorization"] = client_default
        same_value_response = client.send(same_value)

        deleted_after_add = client.build_request(GET, url)
        deleted_after_add.headers["X-Auth-Proof"] = "temporary"
        del deleted_after_add.headers["X-Auth-Proof"]
        deleted_after_add_response = client.send(deleted_after_add)

    assert header_values(same_value_response.json(), "authorization") == [client_default]
    assert "x-auth-proof" not in deleted_after_add_response.json()["headers"]


def test_sync_replaced_prepared_headers_remain_authoritative(
    sync_http_server: str,
) -> None:
    client_default = "Bearer client-default"

    def authenticate(_request: AuthRequest) -> dict[str, str]:
        return {
            "Authorization": "Bearer auth",
            "X-Auth-Proof": "auth-proof",
        }

    url = f"{sync_http_server}{SECURITY_HEADERS_PATH}"

    with foghttp.Client(
        headers={"Authorization": client_default},
        auth=authenticate,
    ) as client:
        request = client.build_request(GET, url)
        replacement = request.headers.copy()
        replacement["Authorization"] = client_default
        request.headers = replacement
        response = client.send(request)

        deleted = client.build_request(GET, url)
        deleted.headers = deleted.headers.copy()
        deleted.headers["X-Auth-Proof"] = "temporary"
        del deleted.headers["X-Auth-Proof"]
        deleted_response = client.send(deleted)

    assert header_values(response.json(), "authorization") == [client_default]
    assert "x-auth-proof" not in deleted_response.json()["headers"]


def test_sync_auth_can_manage_header_after_redirect_drops_request_owned_value(
    sync_http_server: str,
) -> None:
    observed_content_types: list[str | None] = []

    def authenticate(request: AuthRequest) -> dict[str, str]:
        observed_content_types.append(foghttp.Headers(request.headers).get("content-type"))
        return {"Content-Type": f"application/auth-hop-{request.redirect_hop}"}

    location = f"{sync_http_server}{SECURITY_HEADERS_PATH}"
    url = redirect_to_location_url(sync_http_server, status_code=FOUND, location=location)
    with foghttp.Client(auth=authenticate, follow_redirects=True) as client:
        response = client.post(url, json={"ok": True})

    assert observed_content_types == ["application/json", None]
    assert response.history[0].request.headers["content-type"] == "application/json"
    assert header_values(response.json(), "content-type") == ["application/auth-hop-1"]


def test_sync_deleted_prepared_header_stays_authoritative_across_redirect(
    sync_http_server: str,
) -> None:
    location = f"{sync_http_server}{SECURITY_HEADERS_PATH}"
    url = redirect_to_location_url(sync_http_server, status_code=FOUND, location=location)
    with foghttp.Client(
        headers={"Authorization": "Bearer client-default"},
        auth=("username", "password"),
        follow_redirects=True,
    ) as client:
        request = client.build_request(GET, url)
        del request.headers["Authorization"]
        response = client.send(request)

    assert "authorization" not in response.history[0].request.headers
    assert header_values(response.json(), "authorization") == []


def test_sync_basic_auth_uses_utf8_credentials(sync_http_server: str) -> None:
    username = "usér"
    second = "pässword"
    with foghttp.Client(auth=(username, second)) as client:
        response = client.get(f"{sync_http_server}{SECURITY_HEADERS_PATH}")

    assert header_values(response.json(), "authorization") == [
        _basic_authorization(username, second),
    ]


def test_sync_basic_auth_is_stripped_on_cross_origin_redirect(
    sync_http_server: str,
    secondary_sync_http_server: str,
) -> None:
    location = f"{secondary_sync_http_server}{SECURITY_HEADERS_PATH}"
    url = redirect_to_location_url(sync_http_server, status_code=FOUND, location=location)
    with foghttp.Client(
        auth=("username", "password"),
        follow_redirects=True,
    ) as client:
        response = client.get(url)

    assert "authorization" in response.history[0].request.headers
    assert header_values(response.json(), "authorization") == []


@pytest.mark.parametrize("streaming", [False, True], ids=("buffered", "streaming"))
def test_sync_callable_auth_refreshes_on_same_origin_redirect(
    sync_http_server: str,
    *,
    streaming: bool,
) -> None:
    requests: list[AuthRequest] = []

    def authenticate(request: AuthRequest) -> dict[str, str]:
        requests.append(request)
        return {
            "Authorization": f"Bearer hop-{request.redirect_hop}",
            "X-Api-Key": f"key-{request.redirect_hop}",
        }

    location = f"{sync_http_server}{SECURITY_HEADERS_PATH}"
    url = redirect_to_location_url(sync_http_server, status_code=FOUND, location=location)
    with foghttp.Client(auth=authenticate, follow_redirects=True) as client:
        if streaming:
            with client.stream(GET, url):
                pass
        else:
            client.get(url)

    assert [request.redirect_hop for request in requests] == [0, 1]


def test_sync_callable_auth_is_disabled_after_cross_origin_redirect(
    sync_http_server: str,
    secondary_sync_http_server: str,
) -> None:
    requests: list[AuthRequest] = []
    default_credential = "default-vendor-proof"
    managed_credential = "auth-vendor-proof"

    def authenticate(request: AuthRequest) -> dict[str, str]:
        requests.append(request)
        return {
            "Authorization": "Bearer secret",
            "X-Vendor-Proof": managed_credential,
        }

    location = f"{secondary_sync_http_server}{SECURITY_HEADERS_PATH}"
    url = redirect_to_location_url(sync_http_server, status_code=FOUND, location=location)
    with foghttp.Client(
        headers={"X-Vendor-Proof": default_credential},
        auth=authenticate,
        follow_redirects=True,
    ) as client:
        response = client.get(url)

    payload = response.json()
    assert [request.redirect_hop for request in requests] == [0]
    assert response.history[0].request.headers["x-vendor-proof"] == managed_credential
    assert header_values(payload, "authorization") == []
    assert "x-vendor-proof" not in response.request.headers
    representation = repr((response.request, response.history))
    assert "Bearer secret" not in representation
    assert managed_credential not in representation
    assert default_credential not in representation


def test_sync_cross_origin_redirect_strips_inactive_auth_header(
    sync_http_server: str,
    secondary_sync_http_server: str,
) -> None:
    default_credential = "default-vendor-proof"
    managed_credential = "auth-vendor-proof"

    def authenticate(request: AuthRequest) -> dict[str, str] | None:
        if request.redirect_hop == 0:
            return {"X-Vendor-Proof": managed_credential}
        return None

    final_location = f"{secondary_sync_http_server}/headers/echo"
    cross_origin_redirect = redirect_to_location_url(
        sync_http_server,
        status_code=FOUND,
        location=final_location,
    )
    url = redirect_to_location_url(
        sync_http_server,
        status_code=FOUND,
        location=cross_origin_redirect,
    )
    with foghttp.Client(
        headers={"X-Vendor-Proof": default_credential},
        auth=authenticate,
        follow_redirects=True,
    ) as client:
        response = client.get(url)

    second_hop = response.history[1].request
    assert second_hop.headers["x-vendor-proof"] == default_credential
    assert default_credential not in repr(second_hop)
    assert response.json().get("x-vendor-proof", []) == []


def test_sync_cross_origin_redirect_strips_all_historical_auth_headers(
    sync_http_server: str,
    secondary_sync_http_server: str,
) -> None:
    def authenticate(request: AuthRequest) -> dict[str, str]:
        if request.redirect_hop == 0:
            return {"X-First-Proof": "auth-first"}
        return {"X-Second-Proof": "auth-second"}

    final_location = f"{secondary_sync_http_server}/headers/echo"
    cross_origin_redirect = redirect_to_location_url(
        sync_http_server,
        status_code=FOUND,
        location=final_location,
    )
    url = redirect_to_location_url(
        sync_http_server,
        status_code=FOUND,
        location=cross_origin_redirect,
    )
    with foghttp.Client(
        headers={
            "X-First-Proof": "default-first",
            "X-Second-Proof": "default-second",
        },
        auth=authenticate,
        follow_redirects=True,
    ) as client:
        response = client.get(url)

    payload = response.json()
    assert payload.get("x-first-proof", []) == []
    assert payload.get("x-second-proof", []) == []


def test_sync_callable_auth_stays_disabled_after_return_to_original_origin(
    sync_http_server: str,
    secondary_sync_http_server: str,
) -> None:
    requests: list[AuthRequest] = []

    def authenticate(request: AuthRequest) -> dict[str, str]:
        requests.append(request)
        return {"Authorization": "Bearer secret", "X-Api-Key": "api-secret"}

    final_location = f"{sync_http_server}{SECURITY_HEADERS_PATH}"
    secondary_location = redirect_to_location_url(
        secondary_sync_http_server,
        status_code=FOUND,
        location=final_location,
    )
    url = redirect_to_location_url(
        sync_http_server,
        status_code=FOUND,
        location=secondary_location,
    )
    with foghttp.Client(auth=authenticate, follow_redirects=True) as client:
        response = client.get(url)

    assert [request.redirect_hop for request in requests] == [0]
    assert len(response.history) == ORIGIN_ROUND_TRIP_REDIRECTS
    assert response.history[0].request.headers["x-api-key"] == "api-secret"
    assert "x-api-key" not in response.history[1].request.headers
    assert header_values(response.json(), "x-api-key") == []


def test_sync_callable_auth_none_removes_previous_headers_on_refresh(
    sync_http_server: str,
) -> None:
    redirect_hops: list[int] = []

    def authenticate(request: AuthRequest) -> dict[str, str] | None:
        redirect_hops.append(request.redirect_hop)
        if request.redirect_hop == 0:
            return {"Authorization": "Bearer initial"}
        return None

    location = f"{sync_http_server}{SECURITY_HEADERS_PATH}"
    url = redirect_to_location_url(sync_http_server, status_code=FOUND, location=location)
    with foghttp.Client(auth=authenticate, follow_redirects=True) as client:
        response = client.get(url)

    assert redirect_hops == [0, 1]
    assert header_values(response.json(), "authorization") == []


def test_sync_shared_prepared_headers_track_mutations_for_each_request(
    sync_http_server: str,
) -> None:
    client_default = "Bearer client-default"

    def authenticate(_request: AuthRequest) -> dict[str, str]:
        return {
            "Authorization": "Bearer auth",
            "X-Auth-Proof": "auth-proof",
        }

    url = f"{sync_http_server}{SECURITY_HEADERS_PATH}"
    with foghttp.Client(
        headers={"Authorization": client_default},
        auth=authenticate,
    ) as client:
        first = client.build_request(GET, url)
        second = client.build_request(GET, url)
        shared = first.headers.copy()
        first.headers = shared
        second.headers = shared
        shared["Authorization"] = client_default
        shared["X-Auth-Proof"] = "temporary"
        del shared["X-Auth-Proof"]

        first_response = client.send(first)
        second_response = client.send(second)

    assert header_values(first_response.json(), "authorization") == [client_default]
    assert header_values(second_response.json(), "authorization") == [client_default]
    assert "x-auth-proof" not in first_response.json()["headers"]
    assert "x-auth-proof" not in second_response.json()["headers"]


def test_sync_callable_auth_restores_client_default_before_redirect_refresh(
    sync_http_server: str,
) -> None:
    default_authorization = "Bearer client-default"
    observed_authorization: list[str] = []

    def authenticate(request: AuthRequest) -> dict[str, str] | None:
        observed_authorization.append(foghttp.Headers(request.headers)["authorization"])
        if len(observed_authorization) == 1:
            return {"Authorization": "Bearer first-hop"}
        return None

    location = f"{sync_http_server}{SECURITY_HEADERS_PATH}"
    url = redirect_to_location_url(sync_http_server, status_code=FOUND, location=location)
    with foghttp.Client(
        headers={"Authorization": default_authorization},
        auth=authenticate,
        follow_redirects=True,
    ) as client:
        response = client.get(url)

    assert observed_authorization == [default_authorization, default_authorization]
    assert response.history[0].request.headers["authorization"] == "Bearer first-hop"
    assert header_values(response.json(), "authorization") == [default_authorization]


def test_sync_callable_auth_accepts_repeated_header_source(sync_http_server: str) -> None:
    def authenticate(_request: AuthRequest) -> foghttp.Headers:
        return foghttp.Headers([("X-Repeat", "one"), ("X-Repeat", "two")])

    with foghttp.Client(auth=authenticate) as client:
        response = client.get(f"{sync_http_server}/headers/echo")

    assert response.json() == {"x-repeat": ["one", "two"]}


@pytest.mark.parametrize("streaming", [False, True], ids=("buffered", "streaming"))
def test_sync_auth_hook_receives_request_extensions(
    sync_http_server: str,
    *,
    streaming: bool,
) -> None:
    observed: list[foghttp.RequestExtensions] = []

    def authenticate(request: AuthRequest) -> None:
        observed.append(request.extensions)

    extensions = {"tests.tenant": "tenant-1"}
    with foghttp.Client(auth=authenticate) as client:
        if streaming:
            with client.stream(GET, sync_http_server, extensions=extensions):
                pass
        else:
            client.get(sync_http_server, extensions=extensions)

    assert observed == [foghttp.RequestExtensions(extensions)]


def test_sync_auth_hook_failure_occurs_before_transport_acquire(sync_http_server: str) -> None:
    def authenticate(_request: AuthRequest) -> dict[str, str]:
        raise RuntimeError(AUTH_REFRESH_FAILURE)

    with foghttp.Client(auth=authenticate) as client:
        with pytest.raises(RuntimeError, match="auth refresh failed"):
            client.get(sync_http_server)
        stats = client.stats()

    assert stats.total_requests == 1
    assert stats.failed_requests == 1
    assert stats.active_requests == 0
    assert stats.pool_acquire_attempts == 0


def test_sync_auth_hook_rejects_transport_managed_headers(sync_http_server: str) -> None:
    def authenticate(_request: AuthRequest) -> dict[str, str]:
        return {"Host": "other.example"}

    with foghttp.Client(auth=authenticate) as client:  # noqa: SIM117
        with pytest.raises(ValueError, match="managed by FogHTTP transport"):
            client.get(sync_http_server)


def test_sync_auth_hook_rejects_awaitable_result(sync_http_server: str) -> None:
    async def headers() -> dict[str, str]:
        return {"Authorization": "Bearer token"}

    def authenticate(_request: AuthRequest) -> HeaderSource:
        return cast("HeaderSource", headers())

    with foghttp.Client(auth=authenticate) as client:  # noqa: SIM117
        with pytest.raises(TypeError, match="auth hook must return HTTP headers or None"):
            client.get(sync_http_server)


@pytest.mark.parametrize(
    "result",
    [
        pytest.param(object(), id="not-a-header-source"),
        pytest.param([("X-Auth", object())], id="non-string-header-value"),
    ],
)
def test_sync_auth_hook_rejects_malformed_header_source(
    sync_http_server: str,
    result: object,
) -> None:
    def authenticate(_request: AuthRequest) -> HeaderSource:
        return cast("HeaderSource", result)

    with foghttp.Client(auth=authenticate) as client:  # noqa: SIM117
        with pytest.raises(TypeError, match="auth hook must return HTTP headers or None"):
            client.get(sync_http_server)


def test_sync_auth_does_not_override_body_managed_content_type(sync_http_server: str) -> None:
    def authenticate(_request: AuthRequest) -> dict[str, str]:
        return {"Content-Type": "application/auth"}

    with foghttp.Client(auth=authenticate) as client:
        response = client.post(
            f"{sync_http_server}{SECURITY_HEADERS_PATH}",
            json={"ok": True},
        )

    assert header_values(response.json(), "content-type") == ["application/json"]


def test_sync_custom_auth_header_is_redacted_from_request_info_repr(
    sync_http_server: str,
    faker: Faker,
) -> None:
    secret = faker.sha256()

    def authenticate(_request: AuthRequest) -> dict[str, str]:
        return {"X-Vendor-Signature": secret}

    with foghttp.Client(auth=authenticate) as client:
        response = client.get(sync_http_server)

    assert response.request.headers["x-vendor-signature"] == secret
    assert secret not in repr(response.request)
    assert "<redacted>" in repr(response.request)
    assert secret not in repr(foghttp.Headers(response.request.headers))
    assert secret not in repr(response.request.headers.copy())


def test_sync_auth_credentials_are_absent_from_errors_and_telemetry(
    sync_http_server: str,
    faker: Faker,
) -> None:
    secret = faker.sha256()
    sink = RecordingTelemetrySink()

    def authenticate(_request: AuthRequest) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {secret}",
            "X-Vendor-Signature": secret,
        }

    with (
        foghttp.Client(
            auth=authenticate,
            limits=foghttp.Limits(max_response_body_size=1),
            telemetry=TelemetryConfig(sink=sink),
        ) as client,
        pytest.raises(foghttp.ResponseBodyTooLargeError) as captured,
    ):
        client.get(f"{sync_http_server}/bytes/2")

    assert secret not in str(captured.value)
    assert secret not in repr(captured.value)
    assert secret not in repr(sink.events)


def _basic_authorization(username: str, password: str) -> str:
    token = b64encode(f"{username}:{password}".encode()).decode("ascii")
    return f"Basic {token}"
