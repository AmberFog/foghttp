from foghttp import AsyncClient, Client
from foghttp.methods import GET


def send_sync_request(client: Client, url: str, *, streaming: bool) -> None:
    if not streaming:
        client.get(url)
        return

    with client.stream(GET, url):
        pass


async def send_async_request(client: AsyncClient, url: str, *, streaming: bool) -> None:
    if not streaming:
        await client.get(url)
        return

    async with client.stream(GET, url):
        pass
