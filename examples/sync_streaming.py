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
from foghttp.methods import GET


def main() -> None:
    with (
        foghttp.Client() as client,
        client.stream(GET, "https://httpbin.org/stream-bytes/65536") as response,
    ):
        response.raise_for_status()

        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)

        print("status:", response.status_code)
        print("bytes:", total)
        print("stats:", client.stats())


if __name__ == "__main__":
    main()
