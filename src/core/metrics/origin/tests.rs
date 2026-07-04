use super::registry::ORIGIN_PRESSURE_CLEANUP_THRESHOLD;
use super::{OriginMetricsRegistry, PendingRequestBlockingReason};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

#[test]
fn registry_reuses_metrics_for_same_origin() {
    let registry = OriginMetricsRegistry::default();

    let first = registry.metrics_for("https://api.example.com");
    let second = registry.metrics_for("https://api.example.com");

    assert!(Arc::ptr_eq(&first, &second));
}

#[test]
fn registry_snapshots_are_sorted_by_origin() {
    let registry = OriginMetricsRegistry::default();
    registry.metrics_for("https://z.example.com");
    registry.metrics_for("https://a.example.com");

    let origins = registry
        .snapshots()
        .into_iter()
        .map(|snapshot| snapshot.origin)
        .collect::<Vec<_>>();

    assert_eq!(
        origins,
        vec![
            "https://a.example.com".to_owned(),
            "https://z.example.com".to_owned(),
        ]
    );
}

#[test]
fn registry_pruning_marks_historical_origin_pressure_incomplete() {
    let registry = OriginMetricsRegistry::default();

    for origin_index in 0..ORIGIN_PRESSURE_CLEANUP_THRESHOLD {
        registry.metrics_for(&format!("https://{origin_index}.example.com"));
    }
    assert!(registry.snapshots_include_all_historical_origins());

    registry.metrics_for("https://new.example.com");

    assert!(!registry.snapshots_include_all_historical_origins());
    assert_eq!(registry.snapshots().len(), 1);
    assert_eq!(registry.snapshots()[0].origin, "https://new.example.com");
}

#[test]
fn origin_pool_diagnostics_reports_pending_waiter_reason() {
    let registry = OriginMetricsRegistry::default();
    let metrics = registry.metrics_for("https://api.example.com");

    let waiter_id =
        metrics.pending_request_started(PendingRequestBlockingReason::GlobalActiveRequests);
    let blocked_snapshot = metrics.pool_diagnostics_snapshot();

    assert_eq!(blocked_snapshot.pending_requests, 1);
    assert_eq!(
        blocked_snapshot.blocked_by,
        PendingRequestBlockingReason::GlobalActiveRequests
    );

    metrics.pending_request_finished(waiter_id);
    let idle_snapshot = metrics.pool_diagnostics_snapshot();

    assert_eq!(idle_snapshot.pending_requests, 0);
    assert_eq!(idle_snapshot.blocked_by, PendingRequestBlockingReason::None);
}

#[test]
fn origin_pool_diagnostics_reports_mixed_pending_waiter_reasons() {
    let registry = OriginMetricsRegistry::default();
    let metrics = registry.metrics_for("https://api.example.com");

    let global_waiter =
        metrics.pending_request_started(PendingRequestBlockingReason::GlobalActiveRequests);
    let origin_waiter =
        metrics.pending_request_started(PendingRequestBlockingReason::PerOriginActiveRequests);

    let snapshot = metrics.pool_diagnostics_snapshot();

    assert_eq!(snapshot.pending_requests, 2);
    assert_eq!(snapshot.blocked_by, PendingRequestBlockingReason::Mixed);

    metrics.pending_request_finished(global_waiter);
    metrics.pending_request_finished(origin_waiter);
}

#[test]
fn origin_snapshot_reports_last_used_and_idle_age() {
    let registry = OriginMetricsRegistry::default();
    let metrics = registry.metrics_for("https://api.example.com");

    metrics.connection_opened();
    metrics.connection_became_idle();
    thread::sleep(Duration::from_millis(1));

    let idle_snapshot = metrics.snapshot();

    assert_eq!(idle_snapshot.active_connections, 1);
    assert_eq!(idle_snapshot.idle_connections, 1);
    assert!(idle_snapshot.last_used_at_ns > 0);
    assert!(idle_snapshot.idle_age_ns > 0);
    assert_eq!(
        idle_snapshot.last_activity_at_ns,
        idle_snapshot.last_used_at_ns
    );

    metrics.connection_left_idle();
    let active_snapshot = metrics.snapshot();

    assert_eq!(active_snapshot.idle_connections, 0);
    assert_eq!(active_snapshot.idle_age_ns, 0);
    assert!(active_snapshot.last_used_at_ns >= idle_snapshot.last_used_at_ns);
}

#[test]
fn origin_idle_age_survives_partial_idle_drain_and_restarts_after_full_drain() {
    let registry = OriginMetricsRegistry::default();
    let metrics = registry.metrics_for("https://api.example.com");

    metrics.connection_opened();
    metrics.connection_opened();
    metrics.connection_became_idle();
    thread::sleep(Duration::from_millis(1));
    metrics.connection_became_idle();

    let both_idle_snapshot = metrics.snapshot();

    assert_eq!(both_idle_snapshot.idle_connections, 2);
    assert!(both_idle_snapshot.idle_age_ns > 0);

    metrics.connection_left_idle();
    let partial_drain_snapshot = metrics.snapshot();

    assert_eq!(partial_drain_snapshot.idle_connections, 1);
    assert!(partial_drain_snapshot.idle_age_ns > 0);

    metrics.connection_left_idle();
    let drained_snapshot = metrics.snapshot();

    assert_eq!(drained_snapshot.idle_connections, 0);
    assert_eq!(drained_snapshot.idle_age_ns, 0);

    metrics.connection_became_idle();
    thread::sleep(Duration::from_millis(1));
    let restarted_snapshot = metrics.snapshot();

    assert_eq!(restarted_snapshot.idle_connections, 1);
    assert!(restarted_snapshot.idle_age_ns > 0);
}
