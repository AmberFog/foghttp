__all__ = ("decompression_server",)

from collections.abc import Callable, Iterator
from contextlib import ExitStack

import pytest

from .payloads import EncodedResponse
from .server import DecompressionServer, start_decompression_server


@pytest.fixture
def decompression_server() -> Iterator[Callable[[EncodedResponse], DecompressionServer]]:
    with ExitStack() as stack:

        def start(response: EncodedResponse) -> DecompressionServer:
            return stack.enter_context(start_decompression_server(response))

        yield start
