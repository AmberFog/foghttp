# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "foghttp",
# ]
#
# [tool.uv.sources]
# foghttp = { path = "../", editable = true }
# ///

from os import environ

import foghttp


DEFAULT_TARGET_URL = "https://httpbin.org/get"


def main() -> None:
    proxy = environ.get("FOGHTTP_HTTP_PROXY") or None
    target_url = environ.get("FOGHTTP_PROXY_TARGET_URL", DEFAULT_TARGET_URL)

    with foghttp.Client(proxy=proxy) as client:
        response = client.get(target_url)
        response.raise_for_status()

        print("proxy:", proxy or "direct")
        print("target:", target_url)
        print("status:", response.status_code)
        print("request:", response.request.method, response.request.url)


if __name__ == "__main__":
    main()
