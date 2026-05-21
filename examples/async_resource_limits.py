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
    "https://httpbin.org/delay/1?item=1",
    "https://httpbin.org/delay/1?item=2",
    "https://httpbin.org/delay/1?item=3",
    "https://httpbin.org/delay/1?item=4",
    "https://httpbin.org/get?item=5",
]


async def fetch(client: foghttp.AsyncClient, url: str) -> None:
    response = await client.get(url)
    response.raise_for_status()
    print(response.status_code, response.request.url)


async def main() -> None:
    limits = foghttp.Limits(
        max_active_requests=4,
        max_active_requests_per_origin=2,
        max_pending_requests=20,
        max_response_body_size=1024 * 1024,
        max_buffered_response_bytes=4 * 1024 * 1024,
    )
    timeouts = foghttp.Timeouts(
        connect=2.0,
        pool=2.0,
        total=15.0,
    )

    async with foghttp.AsyncClient(limits=limits, timeouts=timeouts) as client:
        await asyncio.gather(*(fetch(client, url) for url in URLS))
        print(client.stats())
        print(client.dump_pool_diagnostics())


if __name__ == "__main__":
    asyncio.run(main())
