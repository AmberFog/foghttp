import subprocess
import sys

import pytest


def test_import_and_disabled_requests_never_import_opentelemetry(sync_http_server: str) -> None:
    script = """
import asyncio
import builtins
import sys

original_import = builtins.__import__

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 0 and (name == "opentelemetry" or name.startswith("opentelemetry.")):
        raise AssertionError("disabled tracing imported OpenTelemetry")
    return original_import(name, globals, locals, fromlist, level)

builtins.__import__ = guarded_import
import foghttp
from foghttp.opentelemetry import OpenTelemetryTracing

url = sys.argv[1]
with foghttp.Client(trust_env=False) as client:
    assert client.get(url).status_code == 200
    with client.stream("GET", url) as response:
        assert b"".join(response.iter_bytes())

async def run():
    async with foghttp.AsyncClient(trust_env=False) as client:
        assert (await client.get(url)).status_code == 200
        async with client.stream("GET", url) as response:
            assert b"".join([chunk async for chunk in response.aiter_bytes()])

asyncio.run(run())
assert not any(name == "opentelemetry" or name.startswith("opentelemetry.") for name in sys.modules)
"""
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-c", script, sync_http_server],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("missing_module", ["opentelemetry", "opentelemetry.context"])
def test_missing_api_is_reported_only_when_constructing_integration(missing_module: str) -> None:
    script = """
import importlib.abc
import sys

missing_module = sys.argv[1]
if missing_module != "opentelemetry":
    import opentelemetry

class MissingAPI(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "opentelemetry" or fullname.startswith("opentelemetry."):
            raise ModuleNotFoundError("optional API is absent", name=missing_module)

sys.meta_path.insert(0, MissingAPI())
import foghttp
from foghttp.opentelemetry import OpenTelemetryTracing

with foghttp.Client(trust_env=False):
    pass
try:
    OpenTelemetryTracing()
except ImportError as error:
    assert "foghttp[opentelemetry]" in str(error)
else:
    raise AssertionError("missing API was silently ignored")
"""
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-c", script, missing_module],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("failure", ["ImportError", "ModuleNotFoundError"])
def test_unrelated_import_failure_is_not_misreported_as_missing_extra(failure: str) -> None:
    script = """
import importlib.abc
import sys

failure_type = {"ImportError": ImportError, "ModuleNotFoundError": ModuleNotFoundError}[sys.argv[1]]
failure = failure_type("unrelated_dependency_failure", name="unrelated_dependency")

class BrokenAPI(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "opentelemetry" or fullname.startswith("opentelemetry."):
            raise failure

sys.meta_path.insert(0, BrokenAPI())
from foghttp.opentelemetry import OpenTelemetryTracing

try:
    OpenTelemetryTracing()
except ImportError as error:
    assert error is failure
    assert "foghttp[opentelemetry]" not in str(error)
else:
    raise AssertionError("unrelated import failure was ignored")
"""
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-c", script, failure],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_api_only_requests_need_neither_sdk_nor_global_provider(sync_http_server: str) -> None:
    script = """
import asyncio
import importlib.abc
import sys

class MissingSDK(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "opentelemetry.sdk" or fullname.startswith("opentelemetry.sdk."):
            raise AssertionError("FogHTTP attempted to import the optional SDK")

sys.meta_path.insert(0, MissingSDK())
from opentelemetry import trace
import foghttp
from foghttp.opentelemetry import OpenTelemetryTracing

provider = trace.get_tracer_provider()
tracing = OpenTelemetryTracing()
url = sys.argv[1]
with foghttp.Client(trust_env=False, tracing=tracing) as client:
    assert client.get(url).status_code == 200
    with client.stream("GET", url) as response:
        assert b"".join(response.iter_bytes())

async def run():
    async with foghttp.AsyncClient(trust_env=False, tracing=tracing) as client:
        assert (await client.get(url)).status_code == 200
        async with client.stream("GET", url) as response:
            assert b"".join([chunk async for chunk in response.aiter_bytes()])

asyncio.run(run())
assert trace.get_tracer_provider() is provider
assert not any(name.startswith("opentelemetry.sdk") for name in sys.modules)
"""
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-c", script, sync_http_server],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
