from prometheus_client import CollectorRegistry
from prometheus_client.openmetrics.exposition import generate_latest
import pytest

from foghttp import TransportStats
from foghttp.prometheus import PrometheusTransportStatsCollector


_STATS_METRIC_COUNT = 13


def test_stats_collector_sums_alert_oriented_snapshots() -> None:
    first = TransportStats(
        active_requests=2,
        pending_requests=3,
        pool_acquire_timeouts=5,
        connection_acquire_timeouts=7,
        active_connections=11,
        idle_connections=13,
        connections_opened=17,
        connections_open_failed=19,
        connections_closed=23,
        connections_reused=29,
        connections_aborted=31,
        buffered_response_bytes=37,
        buffered_response_budget_rejections=41,
    )
    second = TransportStats(
        active_requests=43,
        pending_requests=47,
        pool_acquire_timeouts=53,
        connection_acquire_timeouts=59,
        active_connections=61,
        idle_connections=67,
        connections_opened=71,
        connections_open_failed=73,
        connections_closed=79,
        connections_reused=83,
        connections_aborted=89,
        buffered_response_bytes=97,
        buffered_response_budget_rejections=101,
    )
    collector = PrometheusTransportStatsCollector(lambda: first, lambda: second)
    registry = CollectorRegistry()
    registry.register(collector)

    expected = {
        "foghttp_active_requests": 45,
        "foghttp_pending_requests": 50,
        "foghttp_pool_acquire_timeouts_total": 58,
        "foghttp_connection_acquire_timeouts_total": 66,
        "foghttp_active_connections": 72,
        "foghttp_idle_connections": 80,
        "foghttp_connections_opened_total": 88,
        "foghttp_connection_open_failures_total": 92,
        "foghttp_connections_closed_total": 102,
        "foghttp_connections_reused_total": 112,
        "foghttp_connections_aborted_total": 120,
        "foghttp_buffered_response_bytes": 134,
        "foghttp_buffered_response_budget_rejections_total": 142,
    }

    assert {metric_name: registry.get_sample_value(metric_name) for metric_name in expected} == expected


def test_describe_does_not_call_stats_provider() -> None:
    def failing_provider() -> TransportStats:
        message = "provider called"
        raise RuntimeError(message)

    collector = PrometheusTransportStatsCollector(failing_provider)

    assert len(tuple(collector.describe())) == _STATS_METRIC_COUNT
    with pytest.raises(RuntimeError, match="provider called"):
        tuple(collector.collect())


def test_invalid_stats_provider_result_fails_the_scrape() -> None:
    def invalid_provider() -> object:
        return object()

    collector = PrometheusTransportStatsCollector(invalid_provider)  # type: ignore[arg-type]
    registry = CollectorRegistry()
    registry.register(collector)

    with pytest.raises(TypeError, match="TransportStats"):
        generate_latest(registry)


@pytest.mark.parametrize(
    "snapshot",
    [
        pytest.param(TransportStats(active_requests=-1), id="negative-gauge"),
        pytest.param(TransportStats(pool_acquire_timeouts=-1), id="negative-counter"),
        pytest.param(TransportStats(active_requests=True), id="boolean"),
        pytest.param(TransportStats(active_requests=1.5), id="fractional"),  # type: ignore[arg-type]
    ],
)
def test_invalid_stats_values_fail_before_a_metric_family_is_emitted(
    snapshot: TransportStats,
) -> None:
    collector = PrometheusTransportStatsCollector(lambda: snapshot)

    with pytest.raises(ValueError, match="non-negative integers"):
        tuple(collector.collect())


def test_stats_collector_requires_at_least_one_provider() -> None:
    with pytest.raises(ValueError, match="stats provider"):
        PrometheusTransportStatsCollector()


def test_stats_collector_rejects_non_callable_provider() -> None:
    with pytest.raises(TypeError, match="stats provider"):
        PrometheusTransportStatsCollector(None)  # type: ignore[arg-type]
