__all__ = (
    "BYTES_64K",
    "ECHO_64K",
    "HTTP_REASONS",
    "POST_JSON",
    "REDIRECT_BODY",
    "SMALL_JSON",
    "SMALL_JSON_OBJECT",
    "scenarios",
)

import importlib
import json
from typing import Any

from bench.constants import BENCHMARK_SEED
from bench.models import Scenario


POOL_CONTENTION_CONNECTIONS = 10

HTTP_REASONS = {
    200: "OK",
    301: "Moved Permanently",
    302: "Found",
    303: "See Other",
    307: "Temporary Redirect",
    308: "Permanent Redirect",
    404: "Not Found",
}

SMALL_JSON_OBJECT = {
    "ok": True,
    "message": "foghttp benchmark",
    "items": [1, 2, 3, 4],
    "meta": {
        "client": "local",
        "shape": "small-json",
    },
}
SMALL_JSON = json.dumps(SMALL_JSON_OBJECT, separators=(",", ":")).encode()
BYTES_64K = b"x" * 65536
ECHO_64K = b"y" * 65536
REDIRECT_BODY = b"redirect-body"
POST_JSON = {
    "name": "Ada Lovelace",
    "file_name": "benchmark.json",
    "email": "ada@example.test",
    "tags": ["foghttp", "benchmark", "json"],
    "active": True,
}


def scenarios() -> dict[str, Scenario]:
    return {
        "json-small": Scenario(
            name="json-small",
            method="GET",
            path="/json-small",
            expected_content_length=len(SMALL_JSON),
            description="GET small buffered JSON, status and body length check.",
        ),
        "json-decode-small": Scenario(
            name="json-decode-small",
            method="GET",
            path="/json-small",
            expected_json_keys=("ok", "message", "items"),
            description="GET small JSON and call the client's JSON decoder.",
        ),
        "bytes-64k": Scenario(
            name="bytes-64k",
            method="GET",
            path="/bytes-64k",
            expected_content_length=len(BYTES_64K),
            description="GET 64 KiB buffered body.",
        ),
        "post-json-echo": Scenario(
            name="post-json-echo",
            method="POST",
            path="/echo",
            json_body=build_post_json(),
            expected_json_keys=("name", "file_name", "email", "tags"),
            description="POST JSON using each client's JSON request API and decode echoed JSON.",
        ),
        "post-echo-64k": Scenario(
            name="post-echo-64k",
            method="POST",
            path="/echo",
            body=ECHO_64K,
            expected_content_length=len(ECHO_64K),
            description="POST 64 KiB bytes and read the echoed body.",
        ),
        "redirect-get-302": redirect_scenario(
            name="redirect-get-302",
            method="GET",
            status_code=302,
            target="json-small",
            description="GET through a 302 redirect and decode final JSON.",
        ),
        "redirect-head-302": Scenario(
            name="redirect-head-302",
            method="HEAD",
            path="/redirect/302/json-small",
            expected_content_length=0,
            expected_redirects=1,
            expected_final_path="/json-small",
            follow_redirects=True,
            description="HEAD through a 302 redirect with no response body.",
        ),
        "redirect-post-303": redirect_scenario(
            name="redirect-post-303",
            method="POST",
            status_code=303,
            target="json-small",
            body=REDIRECT_BODY,
            description="POST through a 303 redirect, rewritten to GET.",
        ),
        "redirect-post-307": Scenario(
            name="redirect-post-307",
            method="POST",
            path="/redirect/307/echo",
            body=REDIRECT_BODY,
            expected_content_length=len(REDIRECT_BODY),
            expected_redirects=1,
            expected_final_path="/echo",
            follow_redirects=True,
            description="POST through a 307 redirect, preserving method and body.",
        ),
        "delay-20ms": Scenario(
            name="delay-20ms",
            method="GET",
            path="/delay/20",
            expected_json_keys=("ok", "message", "items"),
            description="GET with 20 ms server delay to compare scheduling overhead.",
        ),
        "pool-contention-20ms": Scenario(
            name="pool-contention-20ms",
            method="GET",
            path="/delay/20",
            expected_json_keys=("ok", "message", "items"),
            max_connections=POOL_CONTENTION_CONNECTIONS,
            description="GET with 20 ms delay and a fixed 10-connection pool.",
        ),
    }


def build_post_json() -> dict[str, Any]:
    try:
        faker_module = importlib.import_module("faker")
    except ImportError:
        return POST_JSON

    faker = faker_module.Faker()
    faker.seed_instance(BENCHMARK_SEED)
    return {
        "name": faker.name(),
        "file_name": faker.file_name(extension="json"),
        "email": faker.email(),
        "tags": [faker.word() for _ in range(3)],
        "active": True,
    }


def redirect_scenario(
    *,
    name: str,
    method: str,
    status_code: int,
    target: str,
    description: str,
    body: bytes | None = None,
) -> Scenario:
    return Scenario(
        name=name,
        method=method,
        path=f"/redirect/{status_code}/{target}",
        body=body,
        expected_json_keys=("ok", "message", "items"),
        expected_redirects=1,
        expected_final_path=f"/{target}",
        follow_redirects=True,
        description=description,
    )
