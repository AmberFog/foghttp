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


TARGET_URL = "http://httpbin.org/get"


def main() -> None:
    proxy = environ.get("FOGHTTP_HTTP_PROXY") or None

    with foghttp.Client(proxy=proxy) as client:
        response = client.get(TARGET_URL)
        response.raise_for_status()

        print("proxy:", proxy or "direct")
        print("status:", response.status_code)
        print("request:", response.request.method, response.request.url)


if __name__ == "__main__":
    main()
