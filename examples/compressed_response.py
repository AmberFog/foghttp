# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "foghttp",
# ]
#
# [tool.uv.sources]
# foghttp = { path = "../", editable = true }
# ///

import json

import foghttp


def main() -> None:
    with foghttp.Client(
        base_url="https://httpbin.org",
        headers={"accept": "application/json", "accept-encoding": "gzip, deflate, br"},
    ) as client:
        response = client.get("gzip")
        response.raise_for_status()

        print("status:", response.status_code)
        print("content-encoding:", response.headers.get("content-encoding"))
        print("json:", json.dumps(response.json(), sort_keys=True))


if __name__ == "__main__":
    main()
