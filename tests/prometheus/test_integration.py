from io import BytesIO
from typing import Any

from prometheus_client import CollectorRegistry, make_asgi_app, make_wsgi_app
from prometheus_client.openmetrics.exposition import generate_latest

import foghttp
from foghttp.prometheus import (
    PrometheusTelemetrySink,
    PrometheusTransportStatsCollector,
)
from foghttp.status_codes.success import OK


def _assert_successful_request_scrape(registry: CollectorRegistry) -> None:
    payload = generate_latest(registry).decode()
    assert (
        registry.get_sample_value(
            "foghttp_requests_total",
            {
                "method": "GET",
                "origin": "all",
                "status_class": "2xx",
                "outcome": "success",
            },
        )
        == 1
    )
    assert registry.get_sample_value("foghttp_active_requests") == 0
    assert registry.get_sample_value("foghttp_connections_opened_total") == 1
    assert "# EOF" in payload


def test_sync_client_exports_events_and_stats(sync_http_server: str) -> None:
    registry = CollectorRegistry()
    sink = PrometheusTelemetrySink(registry=registry)

    with foghttp.Client(
        telemetry=foghttp.TelemetryConfig(sink=sink, on_hook_error="warn"),
    ) as client:
        collector = PrometheusTransportStatsCollector(client.stats)
        registry.register(collector)
        response = client.get(f"{sync_http_server}/status/{OK}")
        assert response.status_code == OK
        _assert_successful_request_scrape(registry)
        registry.unregister(collector)


async def test_async_client_exports_events_and_stats(http_server: str) -> None:
    registry = CollectorRegistry()
    sink = PrometheusTelemetrySink(registry=registry)

    async with foghttp.AsyncClient(
        telemetry=foghttp.TelemetryConfig(sink=sink, on_hook_error="warn"),
    ) as client:
        collector = PrometheusTransportStatsCollector(client.stats)
        registry.register(collector)
        response = await client.get(f"{http_server}/status/{OK}")
        assert response.status_code == OK
        _assert_successful_request_scrape(registry)
        registry.unregister(collector)


def test_wsgi_exposition_app_scrapes_the_explicit_registry() -> None:
    registry = CollectorRegistry()
    collector = PrometheusTransportStatsCollector(
        lambda: foghttp.TransportStats(active_requests=3),
    )
    registry.register(collector)
    app = make_wsgi_app(registry=registry)
    response_status: list[str] = []

    def start_response(
        status: str,
        headers: list[tuple[str, str]],
    ) -> None:
        response_status.append(status)

    payload = b"".join(
        app(
            {
                "PATH_INFO": "/metrics",
                "QUERY_STRING": "",
                "REQUEST_METHOD": "GET",
                "SERVER_NAME": "metrics.example.test",
                "SERVER_PORT": "80",
                "SERVER_PROTOCOL": "HTTP/1.1",
                "wsgi.input": BytesIO(),
                "wsgi.url_scheme": "http",
            },
            start_response,
        ),
    )

    assert response_status == ["200 OK"]
    assert b"foghttp_active_requests 3" in payload


async def test_asgi_exposition_app_scrapes_the_explicit_registry() -> None:
    registry = CollectorRegistry()
    collector = PrometheusTransportStatsCollector(
        lambda: foghttp.TransportStats(pending_requests=5),
    )
    registry.register(collector)
    app = make_asgi_app(registry=registry)
    sent_messages: list[dict[str, Any]] = []
    request_messages = iter(
        (
            {
                "type": "http.request",
                "body": b"",
                "more_body": False,
            },
        ),
    )

    async def receive() -> dict[str, Any]:
        return next(request_messages)

    async def send(message: dict[str, Any]) -> None:
        sent_messages.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/metrics",
            "raw_path": b"/metrics",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("metrics.example.test", 80),
        },
        receive,
        send,
    )

    assert sent_messages[0]["status"] == OK
    response_body = b"".join(
        message.get("body", b"") for message in sent_messages if message["type"] == "http.response.body"
    )
    assert b"foghttp_pending_requests 5" in response_body
