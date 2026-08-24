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

        print("proxy:", "configured" if proxy is not None else "direct")
        print("target origin:", foghttp.URL(response.request.url).origin)
        print("status:", response.status_code)
        print("request method:", response.request.method)
        if response.is_error:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
