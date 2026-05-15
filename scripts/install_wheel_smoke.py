import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap


SMOKE_SCRIPT = textwrap.dedent(
    """
    import asyncio
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from importlib.metadata import version
    import threading

    import foghttp


    OK_BODY = b"OK"


    class SmokeHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            self.send_response(200)
            self.send_header("content-length", str(len(OK_BODY)))
            self.send_header("connection", "close")
            self.end_headers()
            self.wfile.write(OK_BODY)

        def log_message(self, _format, *_args):
            return


    server = ThreadingHTTPServer(("127.0.0.1", 0), SmokeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    url = f"http://{host}:{port}/smoke"

    try:
        assert version("foghttp")
        assert str(foghttp.URL("HTTPS://Example.COM:443/path?q=1")) == "https://example.com/path?q=1"

        with foghttp.Client() as client:
            response = client.get(url)
            assert response.status_code == 200
            assert response.content == OK_BODY
            assert response.request.method == "GET"

        async def smoke_async_client():
            async with foghttp.AsyncClient() as client:
                response = await client.get(url)
                assert response.status_code == 200
                assert response.content == OK_BODY
                assert response.request.url == url

        asyncio.run(smoke_async_client())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
    """,
)


def main() -> int:
    args = parse_args()
    wheel_path = find_wheel(args.dist_dir)

    with tempfile.TemporaryDirectory() as tmp_dir:
        smoke_dir = Path(tmp_dir)
        target_dir = smoke_dir / "site-packages"
        target_dir.mkdir()

        run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--target",
                str(target_dir),
                str(wheel_path),
            ],
        )
        run([sys.executable, "-c", SMOKE_SCRIPT], cwd=smoke_dir, python_path=target_dir)

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install a built FogHTTP wheel and run a smoke test.")
    parser.add_argument("--dist-dir", type=Path, required=True)
    return parser.parse_args()


def find_wheel(dist_dir: Path) -> Path:
    wheel_paths = sorted(dist_dir.glob("*.whl"))
    if len(wheel_paths) != 1:
        msg = f"expected exactly one wheel in {dist_dir}, found {len(wheel_paths)}"
        raise SystemExit(msg)
    return wheel_paths[0].resolve()


def run(command: list[str], *, cwd: Path | None = None, python_path: Path | None = None) -> None:
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    if python_path is None:
        env.pop("PYTHONPATH", None)
    else:
        env["PYTHONPATH"] = str(python_path)
    subprocess.run(command, check=True, cwd=cwd, env=env)  # noqa: S603


if __name__ == "__main__":
    raise SystemExit(main())
