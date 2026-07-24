# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "foghttp",
# ]
#
# [tool.uv.sources]
# foghttp = { path = "../", editable = true }
# ///

import foghttp


def main() -> None:
    with foghttp.Client(base_url="https://httpbin.org", cookies=True) as client:
        client.get("/cookies/set", params={"foghttp-session": "active"}).raise_for_status()
        response = client.get("/cookies")
        response.raise_for_status()

    print("cookies:", response.json()["cookies"])


if __name__ == "__main__":
    main()
