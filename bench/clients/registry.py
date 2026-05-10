__all__ = ("available_clients",)

import importlib

from bench.clients.aiohttp_client import make_aiohttp_async
from bench.clients.foghttp_client import make_foghttp_async, make_foghttp_sync
from bench.clients.httpx_client import make_httpx_async, make_httpx_sync
from bench.clients.zapros_client import make_zapros_async, make_zapros_sync
from bench.constants import ASYNC_MODE, SYNC_MODE
from bench.models import ClientSpec


def available_clients(
    requested_clients: list[str],
    requested_modes: list[str],
) -> tuple[list[ClientSpec], dict[str, str]]:
    factories = {
        ASYNC_MODE: {
            "foghttp": make_foghttp_async,
            "httpx": make_httpx_async,
            "aiohttp": make_aiohttp_async,
            "zapros": make_zapros_async,
        },
        SYNC_MODE: {
            "foghttp": make_foghttp_sync,
            "httpx": make_httpx_sync,
            "zapros": make_zapros_sync,
        },
    }
    clients: list[ClientSpec] = []
    skipped: dict[str, str] = {}
    for mode in requested_modes:
        mode_factories = factories.get(mode)
        if mode_factories is None:
            skipped[f"{mode}:*"] = "unknown mode"
            continue
        for name in requested_clients:
            factory = mode_factories.get(name)
            if factory is None:
                skipped[f"{mode}:{name}"] = "unknown client"
                continue
            try:
                importlib.import_module(client_module_name(name))
            except Exception as exc:  # noqa: BLE001
                skipped[f"{mode}:{name}"] = f"{type(exc).__name__}: {exc}"
                continue
            clients.append(ClientSpec(name=name, mode=mode, factory=factory))
    return clients, skipped


def client_module_name(name: str) -> str:
    return "foghttp" if name == "foghttp" else name
