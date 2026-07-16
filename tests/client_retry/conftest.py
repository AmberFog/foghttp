from collections.abc import Iterator

import pytest

from .server import RetryTestServer, start_retry_test_server


@pytest.fixture
def retry_server() -> Iterator[RetryTestServer]:
    with start_retry_test_server() as server:
        yield server
