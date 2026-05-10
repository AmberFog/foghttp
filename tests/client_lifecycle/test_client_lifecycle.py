import foghttp

from .helpers import CloseTrackingRawClient


def test_sync_close_closes_raw_client_once(
    sync_client_factory: type[foghttp.Client],
    raw_client: CloseTrackingRawClient,
) -> None:
    client = sync_client_factory()

    client.close()
    client.close()

    assert raw_client.close_calls == 1


def test_sync_context_manager_closes_raw_client(
    sync_client_factory: type[foghttp.Client],
    raw_client: CloseTrackingRawClient,
) -> None:
    with sync_client_factory():
        pass

    assert raw_client.close_calls == 1


async def test_async_close_closes_raw_client_once(
    async_client_factory: type[foghttp.AsyncClient],
    raw_client: CloseTrackingRawClient,
) -> None:
    client = async_client_factory()

    await client.aclose()
    await client.aclose()

    assert raw_client.close_calls == 1


async def test_async_context_manager_closes_raw_client(
    async_client_factory: type[foghttp.AsyncClient],
    raw_client: CloseTrackingRawClient,
) -> None:
    async with async_client_factory():
        pass

    assert raw_client.close_calls == 1
