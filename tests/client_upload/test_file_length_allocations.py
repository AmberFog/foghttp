import json
import subprocess
import sys

import pytest

from tests.client_upload.file_length_allocation_probe import ALLOCATION_BUDGET, PAYLOAD_SIZE, SOURCE_OFFSET


@pytest.mark.parametrize("body_kind", ["content", "files"])
def test_build_request_does_not_copy_live_bytesio_payload(body_kind: str) -> None:
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "tests.client_upload.file_length_allocation_probe", body_kind],
        check=True,
        capture_output=True,
        text=True,
    )
    metrics = json.loads(result.stdout)

    assert metrics["payload_size"] == PAYLOAD_SIZE
    assert metrics["position"] == SOURCE_OFFSET
    assert metrics["content_length"] is not None
    if body_kind == "content":
        assert metrics["content_length"] == PAYLOAD_SIZE - SOURCE_OFFSET
    assert metrics["current"] < ALLOCATION_BUDGET, metrics
    assert metrics["peak"] < ALLOCATION_BUDGET, metrics
