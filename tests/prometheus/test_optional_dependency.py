import subprocess
import sys


def test_importing_foghttp_does_not_import_prometheus_client() -> None:
    script = """
import builtins
import sys

original_import = builtins.__import__


def guarded_import(name, *args, **kwargs):
    if name == "prometheus_client" or name.startswith("prometheus_client."):
        raise AssertionError("foghttp imported its optional Prometheus dependency")
    return original_import(name, *args, **kwargs)


builtins.__import__ = guarded_import
import foghttp

assert "prometheus_client" not in sys.modules
"""

    subprocess.run(  # noqa: S603
        [sys.executable, "-c", script],
        check=True,
        text=True,
        capture_output=True,
    )
