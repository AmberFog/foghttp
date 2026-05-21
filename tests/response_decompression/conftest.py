from collections.abc import Iterator

import pytest

from .server import ResponseDecompressionServer, start_response_decompression_server


@pytest.fixture
def response_decompression_server() -> Iterator[ResponseDecompressionServer]:
    with start_response_decompression_server() as server:
        yield server
