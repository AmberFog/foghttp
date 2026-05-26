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
from foghttp.methods import GET


async def main() -> None:
    async with (
        foghttp.AsyncClient() as client,
        client.stream(GET, "https://httpbin.org/stream-bytes/65536") as response,
    ):
        response.raise_for_status()

        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)

        print("status:", response.status_code)
        print("bytes:", total)
        print("stats:", client.stats())

    async with client.stream(GET, "https://httpbin.org/stream/3") as response:
        response.raise_for_status()
        lines = [line async for line in response.aiter_lines()]

        print("line status:", response.status_code)
        print("lines:", len(lines))


if __name__ == "__main__":
    asyncio.run(main())
