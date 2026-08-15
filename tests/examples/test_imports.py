import os
from pathlib import Path
import py_compile
import sys
from types import ModuleType
import unittest

import pytest

from scripts.wheel_smoke_runtime import discover_examples, loopback_server_url, run_example


EXAMPLES_DIR = Path(__file__).parents[2] / "examples"
EXAMPLE_PATHS = discover_examples(EXAMPLES_DIR)


def test_example_paths_select_sorted_top_level_python_files(tmp_path: Path) -> None:
    first_path = tmp_path / "a.py"
    second_path = tmp_path / "b.py"
    first_path.touch()
    second_path.touch()
    (tmp_path / "ignored.txt").touch()
    nested_dir = tmp_path / "nested"
    nested_dir.mkdir()
    (nested_dir / "ignored.py").touch()
    python_dir = tmp_path / "ignored.py"
    python_dir.mkdir()
    (python_dir / "__main__.py").touch()

    assert discover_examples(tmp_path) == (first_path, second_path)


def test_discover_examples_rejects_empty_inventory(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="no Python examples found"):
        discover_examples(tmp_path)


def test_run_example_uses_import_semantics(tmp_path: Path) -> None:
    example_path = tmp_path / "import_semantics.py"
    example_path.write_text(
        "import sys\n"
        "if __spec__ is None:\n"
        "    raise RuntimeError('missing module spec')\n"
        "if __name__ not in sys.modules:\n"
        "    raise RuntimeError('module is not registered')\n",
        encoding="utf-8",
    )

    module = run_example(example_path)

    assert module.__spec__ is not None
    assert module.__name__ not in sys.modules


def test_run_example_rejects_system_exit(tmp_path: Path) -> None:
    example_path = tmp_path / "exit.py"
    example_path.write_text("raise SystemExit(0)\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="attempted to exit during import"):
        run_example(example_path)


def test_run_example_rejects_skip_control_flow(tmp_path: Path) -> None:
    example_path = tmp_path / "skip.py"
    example_path.write_text(
        "from unittest import SkipTest\nraise SkipTest('not a smoke pass')\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="attempted to skip") as error_info:
        run_example(example_path)

    assert isinstance(error_info.value.__cause__, unittest.SkipTest)


def test_run_example_preserves_ordinary_exception(tmp_path: Path) -> None:
    example_path = tmp_path / "failure.py"
    example_path.write_text("raise LookupError('import failed')\n", encoding="utf-8")

    with pytest.raises(LookupError, match="import failed"):
        run_example(example_path)


def test_run_example_preserves_keyboard_interrupt(tmp_path: Path) -> None:
    example_path = tmp_path / "interrupt.py"
    example_path.write_text("raise KeyboardInterrupt\n", encoding="utf-8")

    with pytest.raises(KeyboardInterrupt):
        run_example(example_path)


@pytest.mark.parametrize("failure_point", ["construct", "start"])
def test_loopback_server_closes_when_thread_setup_fails(
    failure_point: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeServer:
        closed = False

        def serve_forever(self) -> None:
            pytest.fail("server thread must not run")

        def server_close(self) -> None:
            self.closed = True

    class FailingThread:
        def start(self) -> None:
            message = "thread start unavailable"
            raise RuntimeError(message)

    def create_thread(**_kwargs: object) -> FailingThread:
        if failure_point == "construct":
            message = "thread construct unavailable"
            raise RuntimeError(message)
        return FailingThread()

    server = FakeServer()
    monkeypatch.setattr("scripts.wheel_smoke_runtime.ThreadingHTTPServer", lambda *_args: server)
    monkeypatch.setattr("scripts.wheel_smoke_runtime.threading.Thread", create_thread)

    with pytest.raises(RuntimeError, match=f"thread {failure_point} unavailable"), loopback_server_url():
        pytest.fail("context must not be entered")

    assert server.closed


@pytest.mark.parametrize("failure_method", ["shutdown", "server_close", "thread_alive"])
def test_loopback_server_attempts_all_cleanup_after_failure(
    failure_method: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FakeServer:
        server_address = ("127.0.0.1", 80)

        def serve_forever(self) -> None:
            pytest.fail("fake thread must not run")

        def shutdown(self) -> None:
            calls.append("shutdown")
            if failure_method == "shutdown":
                message = "shutdown failed"
                raise RuntimeError(message)

        def server_close(self) -> None:
            calls.append("server_close")
            if failure_method == "server_close":
                message = "server close failed"
                raise RuntimeError(message)

    class FakeThread:
        def start(self) -> None:
            calls.append("start")

        def join(self, *, timeout: int) -> None:
            calls.append(f"join:{timeout}")

        def is_alive(self) -> bool:
            calls.append("is_alive")
            return failure_method == "thread_alive"

    server = FakeServer()
    monkeypatch.setattr("scripts.wheel_smoke_runtime.ThreadingHTTPServer", lambda *_args: server)
    monkeypatch.setattr("scripts.wheel_smoke_runtime.threading.Thread", lambda **_kwargs: FakeThread())

    expected_error = "did not stop" if failure_method == "thread_alive" else "failed"
    with pytest.raises(RuntimeError, match=expected_error), loopback_server_url():
        pass

    assert calls == ["start", "shutdown", "server_close", "join:1", "is_alive"]


def test_run_example_restores_existing_registration_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    example_path = tmp_path / "registered.py"
    example_path.write_text("", encoding="utf-8")
    module_name = run_example(example_path).__name__
    existing_module = ModuleType(module_name)
    monkeypatch.setitem(sys.modules, module_name, existing_module)
    example_path.write_text("raise SystemExit(0)\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="attempted to exit during import"):
        run_example(example_path)

    assert sys.modules[module_name] is existing_module


def test_run_example_ignores_stale_timestamp_bytecode(tmp_path: Path) -> None:
    example_path = tmp_path / "stale.py"
    initial_source = b"pass\n##############\n"
    changed_source = b"raise SystemExit(0)\n"
    assert len(initial_source) == len(changed_source)
    example_path.write_bytes(initial_source)
    metadata = example_path.stat()
    py_compile.compile(
        str(example_path),
        doraise=True,
        invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP,
    )
    example_path.write_bytes(changed_source)
    os.utime(example_path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    assert example_path.stat().st_size == metadata.st_size

    with pytest.raises(RuntimeError, match="attempted to exit during import"):
        run_example(example_path)


@pytest.mark.parametrize("example_path", EXAMPLE_PATHS, ids=lambda path: path.name)
def test_example_imports_without_running_main(example_path: Path) -> None:
    module = run_example(example_path)

    assert module.__name__ != "__main__"
    assert module.__spec__ is not None
    assert module.__spec__.name == module.__name__
