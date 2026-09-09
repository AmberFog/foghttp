"""Manual local streaming controls; run with an explicitly installed release wheel."""

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
import gc
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing
from multiprocessing.connection import Connection
import os
from pathlib import Path
import platform
import resource
import statistics
import subprocess
import sys
import time

import foghttp
import foghttp._foghttp as extension


class StreamingHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        _, size, mode = self.path.split("/")
        chunk_size = int(size)
        chunk = (b"streaming payload\n" * (chunk_size // 18 + 1))[:chunk_size]
        count = 1024 * 1024 // chunk_size
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        frame = f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n"
        try:
            for _ in range(count):
                self.wfile.write(frame)
                if mode == "drip":
                    self.wfile.flush()
                    time.sleep(0.001)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def log_message(self, _format: str, *_args: object) -> None:
        pass


def serve(connection: Connection) -> None:
    with ThreadingHTTPServer(("127.0.0.1", 0), StreamingHandler) as server:
        connection.send(server.server_port)
        connection.close()
        server.serve_forever()


def sync_request(client: foghttp.Client, url: str, mode: str) -> tuple[int, float]:
    started = time.perf_counter()
    if mode == "buffered":
        return len(client.get(url).content), time.perf_counter() - started
    with client.stream("GET", url) as response:
        first = None
        received = 0
        chunks = response.iter_lines() if mode == "lines" else response.iter_bytes()
        for chunk in chunks:
            if first is None:
                first = time.perf_counter() - started
            received += len(chunk)
            if mode == "close":
                break
        return received, first if first is not None else time.perf_counter() - started


async def async_request(client: foghttp.AsyncClient, url: str, mode: str) -> tuple[int, float]:
    started = time.perf_counter()
    if mode == "buffered":
        buffered_response = await client.get(url)
        return len(buffered_response.content), time.perf_counter() - started
    async with client.stream("GET", url) as response:
        first = None
        received = 0
        chunks = response.aiter_lines() if mode == "lines" else response.aiter_bytes()
        async for chunk in chunks:
            if first is None:
                first = time.perf_counter() - started
            received += len(chunk)
            if mode == "close":
                break
        return received, first if first is not None else time.perf_counter() - started


async def async_batch(
    url: str,
    mode: str,
    concurrency: int,
    rounds: int,
) -> tuple[list[tuple[int, float]], float, float, foghttp.TransportStats]:
    async with foghttp.AsyncClient(trust_env=False) as client:
        for _ in range(2):
            await asyncio.gather(*(async_request(client, url, mode) for _ in range(concurrency)))
        started = time.perf_counter()
        cpu = time.process_time()
        samples: list[tuple[int, float]] = []
        for _ in range(rounds):
            samples.extend(await asyncio.gather(*(async_request(client, url, mode) for _ in range(concurrency))))
        elapsed = time.perf_counter() - started
        cpu = time.process_time() - cpu
        stats = client.stats()
    return samples, elapsed, cpu, stats


def sync_batch(
    url: str,
    mode: str,
    concurrency: int,
    rounds: int,
) -> tuple[list[tuple[int, float]], float, float, foghttp.TransportStats]:
    with foghttp.Client(trust_env=False) as client, ThreadPoolExecutor(max_workers=concurrency) as pool:
        for _ in range(2):
            list(pool.map(lambda _: sync_request(client, url, mode), range(concurrency)))
        started = time.perf_counter()
        cpu = time.process_time()
        samples: list[tuple[int, float]] = []
        for _ in range(rounds):
            samples.extend(pool.map(lambda _: sync_request(client, url, mode), range(concurrency)))
        elapsed = time.perf_counter() - started
        cpu = time.process_time() - cpu
        stats = client.stats()
    return samples, elapsed, cpu, stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["bytes", "drip", "close", "lines", "buffered"], default="bytes")
    parser.add_argument("--client", choices=["sync", "async"], required=True)
    parser.add_argument("--size", type=int, choices=[4096, 65536, 262144], default=65536)
    parser.add_argument("--concurrency", type=int, choices=[1, 10], default=1)
    parser.add_argument("--rounds", type=int, default=128)
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("rounds must be positive")
    context = multiprocessing.get_context("spawn")
    reader, writer = context.Pipe(duplex=False)
    server = context.Process(target=serve, args=(writer,))
    server.start()
    writer.close()
    try:
        if not reader.poll(10):
            message = "local server did not start"
            raise TimeoutError(message)
        url = f"http://127.0.0.1:{reader.recv()}/{args.size}/{args.mode}"
        gc.collect()
        rss_command = ["ps", "-o", "rss=", "-p", str(os.getpid())]
        before_rss = int(subprocess.check_output(rss_command))  # noqa: S603 - fixed command and own PID
        arguments = (url, args.mode, args.concurrency, args.rounds)
        samples, elapsed, cpu, stats = (
            asyncio.run(async_batch(*arguments)) if args.client == "async" else sync_batch(*arguments)
        )
        if args.mode != "close" and stats.failed_requests:
            message = f"unexpected failures: {stats.failed_requests}"
            raise RuntimeError(message)
        if args.mode in {"bytes", "drip", "buffered"} and any(size != 1024 * 1024 for size, _ in samples):
            message = "incomplete response"
            raise RuntimeError(message)
        gc.collect()
        after_rss = int(subprocess.check_output(rss_command))  # noqa: S603 - fixed command and own PID
        sys.stdout.write(
            json.dumps(
                {
                    **vars(args),
                    "python": sys.version,
                    "platform": platform.platform(),
                    "extension": str(Path(extension.__file__).resolve()),
                    "pid": os.getpid(),
                    "seconds": elapsed,
                    "client_cpu_seconds": cpu,
                    "mib_per_second": sum(size for size, _ in samples) / 1048576 / elapsed,
                    "first_item_seconds": statistics.median(first for _, first in samples),
                    "rss_before_kib": before_rss,
                    "rss_after_close_kib": after_rss,
                    "rss_peak": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                    "rss_units": "bytes" if sys.platform == "darwin" else "KiB",
                    "failed_requests": stats.failed_requests,
                    "open_failed": stats.connections_open_failed,
                    "active_requests": stats.active_requests,
                },
                sort_keys=True,
            )
            + "\n",
        )
    finally:
        reader.close()
        server.terminate()
        server.join(timeout=5)
        if server.is_alive():
            server.kill()
            server.join()


if __name__ == "__main__":
    main()
