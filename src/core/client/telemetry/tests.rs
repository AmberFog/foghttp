use super::ConnectionTelemetry;
use crate::core::metrics::{Metrics, OriginMetricsSnapshot, ResponseBodyLifecycleOutcome};
use std::sync::Arc;

const ORIGIN: &str = "https://api.example.com";

#[test]
fn telemetry_tracks_reuse_idle_abort_and_close_once() {
    let metrics = Arc::new(Metrics::default());
    let origin_metrics = metrics.origin_metrics(ORIGIN);
    let telemetry = ConnectionTelemetry::new(Arc::clone(&metrics), Some(origin_metrics));

    telemetry
        .response_started()
        .finish(ResponseBodyLifecycleOutcome::ReuseEligible);
    drop(telemetry.response_started());
    telemetry.connection_closed();
    telemetry.connection_closed();

    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.active_connections, 0);
    assert_eq!(snapshot.idle_connections, 0);
    assert_eq!(snapshot.connections_opened, 1);
    assert_eq!(snapshot.connections_closed, 1);
    assert_eq!(snapshot.connections_reused, 1);
    assert_eq!(snapshot.connections_aborted, 1);

    let origin_snapshot = origin_snapshot(&metrics);
    assert_eq!(origin_snapshot.active_connections, 0);
    assert_eq!(origin_snapshot.idle_connections, 0);
    assert_eq!(origin_snapshot.connections_opened, 1);
    assert_eq!(origin_snapshot.connections_closed, 1);
    assert_eq!(origin_snapshot.connections_reused, 1);
    assert_eq!(origin_snapshot.connections_aborted, 1);
}

#[test]
fn closed_connection_does_not_reenter_idle_after_successful_body_finish() {
    let metrics = Arc::new(Metrics::default());
    let origin_metrics = metrics.origin_metrics(ORIGIN);
    let telemetry = ConnectionTelemetry::new(Arc::clone(&metrics), Some(origin_metrics));
    let connection_use = telemetry.response_started();

    telemetry.connection_closed();
    connection_use.finish(ResponseBodyLifecycleOutcome::ReuseEligible);

    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.active_connections, 0);
    assert_eq!(snapshot.idle_connections, 0);
    assert_eq!(snapshot.connections_opened, 1);
    assert_eq!(snapshot.connections_closed, 1);
    assert_eq!(snapshot.connections_reused, 0);
    assert_eq!(snapshot.connections_aborted, 0);

    let origin_snapshot = origin_snapshot(&metrics);
    assert_eq!(origin_snapshot.active_connections, 0);
    assert_eq!(origin_snapshot.idle_connections, 0);
    assert_eq!(origin_snapshot.connections_opened, 1);
    assert_eq!(origin_snapshot.connections_closed, 1);
    assert_eq!(origin_snapshot.connections_reused, 0);
    assert_eq!(origin_snapshot.connections_aborted, 0);
}

fn origin_snapshot(metrics: &Metrics) -> OriginMetricsSnapshot {
    metrics
        .origin_snapshots()
        .into_iter()
        .find(|snapshot| snapshot.origin == ORIGIN)
        .expect("expected origin metrics snapshot")
}
