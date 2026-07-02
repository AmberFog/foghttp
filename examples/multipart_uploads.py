# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "foghttp",
# ]
#
# [tool.uv.sources]
# foghttp = { path = "../", editable = true }
# ///

from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory

import foghttp


BASE_URL = "https://httpbin.org"


def stream_chunks() -> Iterator[bytes]:
    yield b"first chunk\n"
    yield b"second chunk\n"


def main() -> None:
    with TemporaryDirectory() as temp_dir:
        report_path = Path(temp_dir) / "report.txt"
        report_path.write_text("FogHTTP multipart upload\n", encoding="utf-8")

        with foghttp.Client(base_url=BASE_URL) as client:
            with report_path.open("rb") as report:
                response = client.post(
                    "anything/upload",
                    data={"kind": "direct-file"},
                    files={"report": ("report.txt", report, "text/plain")},
                )
            response.raise_for_status()
            print("direct file status:", response.status_code)

            replayable_response = client.post(
                "anything/upload",
                data={"kind": "stream-factory"},
                files={"chunks": ("chunks.txt", stream_chunks, "text/plain")},
            )
            replayable_response.raise_for_status()
            print("stream factory status:", replayable_response.status_code)


if __name__ == "__main__":
    main()
