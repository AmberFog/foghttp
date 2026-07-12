from faker import Faker

import foghttp
from foghttp.methods import GET
from foghttp.policy import TransportPolicyHooks, TransportPolicyRequest
from tests.support.http_routes import SECURITY_HEADERS_PATH


def test_sync_prepared_request_extensions_reach_hooks_and_response(
    sync_http_server: str,
    faker: Faker,
) -> None:
    observed: list[TransportPolicyRequest] = []
    request_id, changed_request_id = faker.uuid4(), faker.uuid4()
    extension_value = faker.uuid4()
    source: dict[str, object] = {
        "tests.request_id": request_id,
        "authorization": extension_value,
    }

    with foghttp.Client(policy_hooks=TransportPolicyHooks(before_send=observed.append)) as client:
        request = client.build_request(
            GET,
            sync_http_server + SECURITY_HEADERS_PATH,
            extensions=source,
        )
        source["tests.request_id"] = changed_request_id
        response = client.send(request)

    assert request.extensions["tests.request_id"] == request_id
    assert observed[0].extensions is request.extensions
    assert response.request.extensions is request.extensions
    assert response.json()["headers"]["authorization"] == []
    assert extension_value not in response.text


def test_sync_prepared_request_extensions_reach_response_without_hooks(
    sync_http_server: str,
    faker: Faker,
) -> None:
    extensions = {"tests.request_id": faker.uuid4()}

    with foghttp.Client() as client:
        request = client.build_request(GET, sync_http_server, extensions=extensions)
        response = client.send(request)

    assert response.request.extensions is request.extensions


async def test_async_prepared_request_extensions_reach_hooks_and_response(
    http_server: str,
    faker: Faker,
) -> None:
    observed: list[TransportPolicyRequest] = []
    request_id, changed_request_id = faker.uuid4(), faker.uuid4()
    extension_value = faker.uuid4()
    source: dict[str, object] = {
        "tests.request_id": request_id,
        "authorization": extension_value,
    }

    async with foghttp.AsyncClient(policy_hooks=TransportPolicyHooks(before_send=observed.append)) as client:
        request = client.build_request(
            GET,
            http_server + SECURITY_HEADERS_PATH,
            extensions=source,
        )
        source["tests.request_id"] = changed_request_id
        response = await client.send(request)

    assert request.extensions["tests.request_id"] == request_id
    assert observed[0].extensions is request.extensions
    assert response.request.extensions is request.extensions
    assert response.json()["headers"]["authorization"] == []
    assert extension_value not in response.text


async def test_async_prepared_request_extensions_reach_response_without_hooks(
    http_server: str,
    faker: Faker,
) -> None:
    extensions = {"tests.request_id": faker.uuid4()}

    async with foghttp.AsyncClient() as client:
        request = client.build_request(GET, http_server, extensions=extensions)
        response = await client.send(request)

    assert response.request.extensions is request.extensions
