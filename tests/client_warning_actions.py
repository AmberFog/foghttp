__all__ = ("collect_unclosed_client",)

from collections.abc import Callable
import gc


def collect_unclosed_client(client_factory: Callable[[], object]) -> None:
    client = client_factory()
    del client
    gc.collect()
