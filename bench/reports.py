__all__ = ("aggregate_results", "write_reports")

from dataclasses import asdict
from importlib import metadata
import json
from pathlib import Path
import platform
import statistics
import sys
import time
from typing import Any

from jinja2 import Environment, FileSystemLoader

from bench.constants import MIN_VARIATION_SAMPLES
from bench.models import BenchmarkArgs, RunResult


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def aggregate_results(results: list[RunResult]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, int, int], list[RunResult]] = {}
    for result in results:
        key = (result.mode, result.client, result.scenario, result.concurrency, result.max_connections)
        grouped.setdefault(key, []).append(result)

    rows: list[dict[str, Any]] = []
    for (mode, client, scenario, concurrency, max_connections), items in sorted(grouped.items()):
        requests_total = sum(item.requests for item in items)
        errors_total = sum(item.errors for item in items)
        rows.append(
            {
                "mode": mode,
                "client": client,
                "scenario": scenario,
                "concurrency": concurrency,
                "max_connections": max_connections,
                "requests": items[0].requests,
                "repeats": len(items),
                "req_s_median": statistics.median(item.requests_per_second for item in items),
                "ok_req_s_median": statistics.median(item.ok_requests_per_second for item in items),
                "req_s_cv_percent": coefficient_of_variation(
                    [item.requests_per_second for item in items],
                ),
                "p50_ms_median": statistics.median(item.p50_ms for item in items),
                "p95_ms_median": statistics.median(item.p95_ms for item in items),
                "p99_ms_median": statistics.median(item.p99_ms for item in items),
                "rss_mb_max": max((item.peak_rss_mb or 0.0) for item in items),
                "threads_max": max((item.peak_threads or 0) for item in items),
                "fds_max": max((item.peak_fds or 0) for item in items),
                "errors_total": errors_total,
                "warmup_errors_total": sum(item.warmup_errors for item in items),
                "error_rate_percent": (errors_total / requests_total) * 100 if requests_total else 0.0,
            },
        )
    return rows


def coefficient_of_variation(values: list[float]) -> float:
    if len(values) < MIN_VARIATION_SAMPLES:
        return 0.0
    mean = statistics.mean(values)
    if mean == 0:
        return 0.0
    return (statistics.stdev(values) / mean) * 100


def write_reports(results: list[RunResult], skipped: dict[str, str], args: BenchmarkArgs) -> None:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    aggregate = aggregate_results(results)
    payload = {
        "metadata": {
            "timestamp": timestamp,
            "python": sys.version,
            "platform": platform.platform(),
            "server": "local asyncio HTTP/1.1 loopback server",
            "args": vars(args),
            "package_versions": package_versions(
                ["foghttp", "httpx", "aiohttp", "zapros", "faker", "jinja2", "psutil", "typer"],
            ),
            "skipped": skipped,
        },
        "aggregate": aggregate,
        "runs": [asdict(result) for result in results],
    }
    json_path = output_dir / f"{timestamp}.json"
    md_path = output_dir / f"{timestamp}.md"
    latest_json = output_dir / "latest.json"
    latest_md = output_dir / "latest.md"

    json_text = json.dumps(payload, indent=2, sort_keys=True)
    json_path.write_text(json_text + "\n")
    latest_json.write_text(json_text + "\n")

    markdown = render_markdown_report(timestamp, aggregate, skipped, args)
    md_path.write_text(markdown)
    latest_md.write_text(markdown)


def render_markdown_report(
    timestamp: str,
    aggregate: list[dict[str, Any]],
    skipped: dict[str, str],
    args: BenchmarkArgs,
) -> str:
    template = report_environment().get_template("report.md.j2")
    return template.render(
        aggregate=aggregate,
        args=args,
        platform_name=platform.platform(),
        python_version=platform.python_version(),
        skipped=skipped,
        timestamp=timestamp,
    )


def report_environment() -> Environment:
    return Environment(
        autoescape=False,  # noqa: S701 - this template renders Markdown, not HTML.
        keep_trailing_newline=True,
        loader=FileSystemLoader(TEMPLATE_DIR),
        lstrip_blocks=True,
        trim_blocks=True,
    )


def package_versions(names: list[str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in names:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "not installed"
    return versions
