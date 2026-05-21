from collections.abc import Iterator

import pytest

from .server import FaultInjectionServer, start_fault_injection_server


@pytest.fixture
def fault_injection_server() -> Iterator[FaultInjectionServer]:
    with start_fault_injection_server() as server:
        yield server
