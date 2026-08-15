import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import import_module
from importlib.metadata import version
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import threading
from types import ModuleType
from typing import cast
from unittest import SkipTest


OK_BODY = b"OK"
OK_STATUS = 200
_MISSING_MODULE = object()


def require(condition: object, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def discover_examples(examples_dir: Path) -> tuple[Path, ...]:
    paths = tuple(path for path in sorted(examples_dir.glob("*.py")) if path.is_file())
    if not paths:
        message = f"no Python examples found in {examples_dir}"
        raise RuntimeError(message)
    return paths


def run_example(example_path: Path) -> ModuleType:
    run_name = f"_foghttp_example_{example_path.stem}"
    previous_module = sys.modules.get(run_name, _MISSING_MODULE)
    spec = spec_from_file_location(run_name, example_path)
    if spec is None or spec.loader is None:
        message = f"cannot create an import spec for Python example: {example_path}"
        raise RuntimeError(message)

    module = module_from_spec(spec)
    sys.modules[run_name] = module
    try:
        try:
            # Compile current bytes so timestamp-based bytecode cannot hide an edited example.
            code = compile(
                example_path.read_bytes(),
                str(example_path),
                "exec",
                dont_inherit=True,
            )
            exec(code, module.__dict__)  # noqa: S102
        except SystemExit as error:
            message = f"Python example attempted to exit during import: {example_path}"
            raise RuntimeError(message) from error
        except SkipTest as error:
            message = f"Python example attempted to skip during import: {example_path}"
            raise RuntimeError(message) from error
        except Exception:
            raise
        except KeyboardInterrupt:
            raise
        except BaseException as error:
            message = f"Python example raised a control-flow exception during import: {example_path}"
            raise RuntimeError(message) from error
    finally:
        if previous_module is _MISSING_MODULE:
            sys.modules.pop(run_name, None)
        else:
            sys.modules[run_name] = cast("ModuleType", previous_module)
    return module


def run_examples(examples_dir: Path) -> None:
    for example_path in discover_examples(examples_dir):
        run_example(example_path)


class SmokeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self.send_response(OK_STATUS)
        self.send_header("content-length", str(len(OK_BODY)))
        self.send_header("connection", "close")
        self.end_headers()
        self.wfile.write(OK_BODY)

    def log_message(self, _format: str, *_args: object) -> None:
        return


@contextmanager
def loopback_server_url() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), SmokeHandler)
    try:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
    except BaseException:
        server.server_close()
        raise

    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/smoke"
    finally:
        try:
            server.shutdown()
        finally:
            try:
                server.server_close()
            finally:
                thread.join(timeout=1)
                if thread.is_alive():
                    message = "loopback HTTP server thread did not stop"
                    raise RuntimeError(message)


def main() -> int:
    _, target_arg, examples_arg = sys.argv
    target_dir = Path(target_arg).resolve()
    examples_dir = Path(examples_arg).resolve()
    sys.path.insert(0, str(target_dir))
    foghttp = import_module("foghttp")

    package_file = getattr(foghttp, "__file__", None)
    require(package_file is not None, "installed foghttp package has no file location")
    require(
        Path(package_file).resolve().is_relative_to(target_dir),
        "foghttp was not imported from the installed wheel target",
    )
    run_examples(examples_dir)

    with loopback_server_url() as url:
        require(bool(version("foghttp")), "installed distribution version is empty")
        require(
            str(foghttp.URL("HTTPS://Example.COM:443/path?q=1")) == "https://example.com/path?q=1",
            "URL normalization smoke failed",
        )

        with foghttp.Client() as client:
            response = client.get(url)
            require(response.status_code == OK_STATUS, "sync response status smoke failed")
            require(response.content == OK_BODY, "sync response body smoke failed")
            require(response.request.method == "GET", "sync request method smoke failed")

        async def smoke_async_client() -> None:
            async with foghttp.AsyncClient() as client:
                response = await client.get(url)
                require(response.status_code == OK_STATUS, "async response status smoke failed")
                require(response.content == OK_BODY, "async response body smoke failed")
                require(response.request.url == url, "async request URL smoke failed")

        asyncio.run(smoke_async_client())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
