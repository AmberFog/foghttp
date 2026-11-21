__all__ = ("ALLOCATION_BUDGET", "PAYLOAD_SIZE", "SOURCE_OFFSET")

import io
import json
import sys
import tracemalloc

import foghttp
from foghttp._request_body import request_body
from foghttp.methods import POST


PAYLOAD_SIZE = 8 * 1024 * 1024
ALLOCATION_BUDGET = PAYLOAD_SIZE // 8
SOURCE_OFFSET = 113
UPLOAD_URL = "https://example.test/upload"


def allocation_metrics(body_kind: str) -> dict[str, int | None]:
    payload = b"x" * PAYLOAD_SIZE
    with io.BytesIO(payload) as source, foghttp.Client() as client:
        source.seek(SOURCE_OFFSET)
        tracemalloc.start()
        try:
            if body_kind == "content":
                request = client.build_request(POST, UPLOAD_URL, content=source)
            elif body_kind == "files":
                request = client.build_request(POST, UPLOAD_URL, files={"file": ("payload.bin", source)})
            else:
                raise ValueError(body_kind)
            current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        return {
            "current": current,
            "peak": peak,
            "position": source.tell(),
            "content_length": request_body(request).content_length,
            "payload_size": len(payload),
        }


if __name__ == "__main__":
    sys.stdout.write(json.dumps(allocation_metrics(sys.argv[1])))
