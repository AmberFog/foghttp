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
    "https://httpbin.org/get?item=3",
]


async def fetch(client: foghttp.AsyncClient, url: str) -> None:
    response = await client.get(url)
    response.raise_for_status()
    print(response.status_code, response.request.url)


async def main() -> None:
    async with foghttp.AsyncClient(
        lifecycle_debug=foghttp.AsyncLifecycleDebugConfig(),
    ) as client:
        tasks = [asyncio.create_task(fetch(client, url)) for url in URLS]
        await asyncio.sleep(0)

        snapshot = client.dump_lifecycle_debug()
        print("active debug requests:", snapshot.active_request_count)
        print("transport active:", snapshot.transport_active_requests)
        print("transport pending:", snapshot.transport_pending_requests)

        await asyncio.gather(*tasks)
        client.assert_no_lifecycle_leaks()


if __name__ == "__main__":
    asyncio.run(main())
