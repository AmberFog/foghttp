__all__ = ("PrometheusTransportStatsCollector",)

from collections.abc import Callable, Iterator, Sequence
from dataclasses import fields

from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, Metric

from ..transport_stats import TransportStats


_StatsProvider = Callable[[], TransportStats]
_PROVIDER_REQUIRED = "PrometheusTransportStatsCollector requires at least one stats provider"
_STATS_RESULT_REQUIRED = "Prometheus stats providers must return TransportStats"
_STATS_VALUES_REQUIRED = "Prometheus TransportStats fields must be non-negative integers"
_TRANSPORT_STATS_FIELD_NAMES = tuple(field.name for field in fields(TransportStats))


class PrometheusTransportStatsCollector:
    """Collect alert-oriented aggregate metrics from one or more clients."""

    __slots__ = ("_stats_providers",)

    def __init__(self, *stats_providers: _StatsProvider) -> None:
        if not stats_providers:
            raise ValueError(_PROVIDER_REQUIRED)
        if not all(callable(provider) for provider in stats_providers):
            raise TypeError(_PROVIDER_REQUIRED)
        self._stats_providers = stats_providers

    def collect(self) -> Iterator[Metric]:
        snapshots = tuple(provider() for provider in self._stats_providers)
        if not all(isinstance(snapshot, TransportStats) for snapshot in snapshots):
            raise TypeError(_STATS_RESULT_REQUIRED)
        _validate_snapshots(snapshots)
        yield from _metric_families(snapshots)

    def describe(self) -> Iterator[Metric]:
        yield from _metric_families(())


def _metric_families(snapshots: Sequence[TransportStats]) -> Iterator[Metric]:
    yield from _gauge_metric_families(snapshots)
    yield from _counter_metric_families(snapshots)


def _validate_snapshots(snapshots: Sequence[TransportStats]) -> None:
    for snapshot in snapshots:
        for field_name in _TRANSPORT_STATS_FIELD_NAMES:
            value = getattr(snapshot, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(_STATS_VALUES_REQUIRED)


def _gauge_metric_families(snapshots: Sequence[TransportStats]) -> Iterator[Metric]:
    yield GaugeMetricFamily(
        "foghttp_active_requests",
        "FogHTTP requests currently executing in the transport.",
        value=sum(snapshot.active_requests for snapshot in snapshots),
    )
    yield GaugeMetricFamily(
        "foghttp_pending_requests",
        "FogHTTP requests currently waiting for a request slot.",
        value=sum(snapshot.pending_requests for snapshot in snapshots),
    )
    yield GaugeMetricFamily(
        "foghttp_active_connections",
        "FogHTTP physical connections currently assigned to requests.",
        value=sum(snapshot.active_connections for snapshot in snapshots),
    )
    yield GaugeMetricFamily(
        "foghttp_idle_connections",
        "FogHTTP physical connections currently idle in pools.",
        value=sum(snapshot.idle_connections for snapshot in snapshots),
    )
    yield GaugeMetricFamily(
        "foghttp_buffered_response_bytes",
        "FogHTTP response bytes currently reserved by buffered responses.",
        value=sum(snapshot.buffered_response_bytes for snapshot in snapshots),
    )


def _counter_metric_families(snapshots: Sequence[TransportStats]) -> Iterator[Metric]:
    yield CounterMetricFamily(
        "foghttp_pool_acquire_timeouts_total",
        "FogHTTP request-slot pool acquire timeouts.",
        value=sum(snapshot.pool_acquire_timeouts for snapshot in snapshots),
    )
    yield CounterMetricFamily(
        "foghttp_connection_acquire_timeouts_total",
        "FogHTTP physical connection-slot acquire timeouts.",
        value=sum(snapshot.connection_acquire_timeouts for snapshot in snapshots),
    )
    yield CounterMetricFamily(
        "foghttp_connections_opened_total",
        "FogHTTP physical connections opened.",
        value=sum(snapshot.connections_opened for snapshot in snapshots),
    )
    yield CounterMetricFamily(
        "foghttp_connection_open_failures_total",
        "FogHTTP physical connection open failures.",
        value=sum(snapshot.connections_open_failed for snapshot in snapshots),
    )
    yield CounterMetricFamily(
        "foghttp_connections_closed_total",
        "FogHTTP physical connections closed.",
        value=sum(snapshot.connections_closed for snapshot in snapshots),
    )
    yield CounterMetricFamily(
        "foghttp_connections_reused_total",
        "FogHTTP requests assigned an existing physical connection.",
        value=sum(snapshot.connections_reused for snapshot in snapshots),
    )
    yield CounterMetricFamily(
        "foghttp_connections_aborted_total",
        "FogHTTP physical connections made non-reusable by abort or body failure.",
        value=sum(snapshot.connections_aborted for snapshot in snapshots),
    )
    yield CounterMetricFamily(
        "foghttp_buffered_response_budget_rejections_total",
        "FogHTTP buffered responses rejected by the aggregate byte budget.",
        value=sum(snapshot.buffered_response_budget_rejections for snapshot in snapshots),
    )
