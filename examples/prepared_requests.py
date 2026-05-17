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
import json

import foghttp
from foghttp.methods import POST


POST_URL = "https://httpbin.org/post"


def print_response(label: str, response: foghttp.Response) -> None:
    data = response.json()
    print(label, "status:", response.status_code)
    print(label, "request:", response.request.method, response.request.url)
    print(label, "trace:", data["headers"].get("X-Trace"))
    print(label, "json:", json.dumps(data.get("json"), sort_keys=True))


def run_sync_example() -> None:
    with foghttp.Client() as client:
        request = client.build_request(
            POST,
            POST_URL,
            json={"name": "Ada Lovelace", "mode": "prepared"},
        )
        request.headers["x-trace"] = "sync-prepared"

        response = client.send(request)
        response.raise_for_status()
        print_response("sync prepared", response)

        manual_request = foghttp.Request(
            POST,
            POST_URL,
            headers={"content-type": "application/json", "x-trace": "sync-manual"},
            content=b'{"name":"Grace Hopper","mode":"manual"}',
        )
        manual_response = client.send(manual_request)
        manual_response.raise_for_status()
        print_response("sync manual", manual_response)


async def run_async_example() -> None:
    async with foghttp.AsyncClient() as client:
        request = client.build_request(
            POST,
            POST_URL,
            json={"name": "Katherine Johnson", "mode": "async-prepared"},
        )
        request.headers["x-trace"] = "async-prepared"

        response = await client.send(request)
        response.raise_for_status()
        print_response("async prepared", response)


def main() -> None:
    run_sync_example()
    asyncio.run(run_async_example())


if __name__ == "__main__":
    main()
