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
    with foghttp.Client() as client:
        with client.stream(GET, "https://httpbin.org/stream-bytes/65536") as response:
            response.raise_for_status()

            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)

            print("status:", response.status_code)
            print("bytes:", total)
            print("stats:", client.stats())

        with client.stream(GET, "https://httpbin.org/stream/3") as response:
            response.raise_for_status()
            lines = list(response.iter_lines())

            print("line status:", response.status_code)
            print("lines:", len(lines))

        with client.stream(GET, "https://httpbin.org/encoding/utf8") as response:
            response.raise_for_status()
            char_count = sum(len(chunk) for chunk in response.iter_text())

            print("text status:", response.status_code)
            print("text chars:", char_count)


if __name__ == "__main__":
    main()
