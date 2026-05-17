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
    with foghttp.Client(base_url="https://httpbin.org") as client:
        response = client.post(
            "post",
            json={"name": "Ada Lovelace", "role": "engineer"},
        )

        response.raise_for_status()
        data = response.json()

        print("status:", response.status_code)
        print("request:", response.request.method, response.request.url)
        print("json:", json.dumps(data["json"], sort_keys=True))


if __name__ == "__main__":
    main()
