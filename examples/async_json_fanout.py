# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "foghttp",
# ]
#
# [tool.uv.sources]
# foghttp = { path = "../", editable = true }
# ///

import asyncio

import foghttp


URLS = [
    "https://httpbin.org/get?item=1",
    "https://httpbin.org/get?item=2",
    "https://httpbin.org/get?item=3",
]


async def fetch(client: foghttp.AsyncClient, url: str) -> None:
    response = await client.get(url)
    response.raise_for_status()
    print(response.status_code, response.request.url)


async def main() -> None:
    limits = foghttp.Limits(
        max_connections=20,
        max_pending_acquires=100,
    )

    async with foghttp.AsyncClient(limits=limits) as client:
        await asyncio.gather(*(fetch(client, url) for url in URLS))
        print(client.stats())


if __name__ == "__main__":
    asyncio.run(main())
