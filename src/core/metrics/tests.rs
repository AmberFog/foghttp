use super::{
    BufferedByteReservationError, Metrics, ResponseBodyLifecycleOutcome, TelemetrySnapshotMetadata,
    TransportStateSnapshot, TELEMETRY_SNAPSHOT_SCHEMA_VERSION,
};
use std::sync::atomic::Ordering;
use std::sync::{Arc, Barrier};
use std::thread;
use std::time::Duration;

const CONCURRENT_SNAPSHOT_COUNT: usize = 32;

#[test]
fn buffered_response_reservation_rejects_without_changing_reserved_bytes() {
    let metrics = Metrics::default();

    assert_eq!(metrics.reserve_buffered_response_bytes(8, Some(8)), Ok(()));
    assert_eq!(
        metrics.reserve_buffered_response_bytes(1, Some(8)),
        Err(BufferedByteReservationError::LimitExceeded)
    );

    assert_eq!(metrics.snapshot().buffered_response_bytes, 8);
}

#[test]
fn buffered_response_release_does_not_underflow_reserved_bytes() {
    let metrics = Metrics::default();

    metrics.release_buffered_response_bytes(8);

    assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
}

#[test]
fn acquire_wait_metrics_track_duration_without_underflowing_pending() {
    let metrics = Metrics::default();

    metrics.pending_request_registered();
    metrics.pool_acquire_started();
    metrics.pool_acquire_waited();
    metrics.pool_acquire_wait_finished(Duration::from_nanos(10));
    metrics.pending_request_finished();
    metrics.pool_acquire_wait_finished(Duration::from_nanos(15));

    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.pending_requests, 0);
    assert_eq!(snapshot.peak_pending_requests, 1);
    assert_eq!(snapshot.pool_acquire_attempts, 1);
    assert_eq!(snapshot.pool_acquire_waited, 1);
    assert_eq!(snapshot.pool_acquire_wait_time_total_ns, 25);
    assert_eq!(snapshot.pool_acquire_wait_time_max_ns, 15);
    assert_eq!(snapshot.pool_acquire_wait_time_last_ns, 15);
}

#[test]
fn transport_state_snapshot_includes_aggregate_metrics_and_origins() {
    let metrics = Metrics::default();

    metrics.request_started();
    metrics.active_request_started();
    let origin_metrics = metrics.origin_metrics("https://api.example.com");
    origin_metrics.active_request_started();
    metrics.pool_acquire_started();
    origin_metrics.pool_acquire_started();
    metrics.pool_acquire_waited();
    origin_metrics.pool_acquire_waited();
    metrics.pool_acquire_wait_finished(Duration::from_nanos(7));
    origin_metrics.pool_acquire_wait_finished(Duration::from_nanos(7));
    let secondary_origin_metrics = metrics.origin_metrics("https://secondary.example.com");
    metrics.pool_acquire_started();
    secondary_origin_metrics.pool_acquire_started();
    metrics.pool_acquire_finished_immediately();
    secondary_origin_metrics.pool_acquire_finished_immediately();

    let snapshot = metrics.transport_state_snapshot();

    assert_eq!(
        snapshot.metadata.schema_version,
        TELEMETRY_SNAPSHOT_SCHEMA_VERSION
    );
    assert!(snapshot.metadata.snapshot_sequence > 0);
    assert_eq!(snapshot.metrics.active_requests, 1);
    assert_eq!(snapshot.metrics.total_requests, 1);
    assert!(snapshot.has_coherent_pressure());
    assert_eq!(snapshot.origins.len(), 2);
    assert_eq!(snapshot.origins[0].origin, "https://api.example.com");
    assert_eq!(snapshot.origins[0].active_requests, 1);
    assert_eq!(snapshot.origins[0].pool_acquire_attempts, 1);
    assert_eq!(snapshot.origins[0].pool_acquire_waited, 1);
    assert_eq!(snapshot.origins[0].pool_acquire_wait_time_total_ns, 7);
    assert_eq!(snapshot.origins[0].pool_acquire_wait_time_max_ns, 7);
    assert_eq!(snapshot.origins[1].origin, "https://secondary.example.com");
    assert_eq!(snapshot.origins[1].pool_acquire_attempts, 1);
    assert_eq!(snapshot.origins[1].pool_acquire_immediate, 1);
}

#[test]
fn telemetry_snapshot_metadata_is_monotonic_and_schema_versioned() {
    let metrics = Metrics::default();

    let first = metrics.next_telemetry_snapshot_metadata();
    let second = metrics.next_telemetry_snapshot_metadata();

    assert_eq!(first.schema_version, TELEMETRY_SNAPSHOT_SCHEMA_VERSION);
    assert_eq!(second.schema_version, TELEMETRY_SNAPSHOT_SCHEMA_VERSION);
    assert!(first.snapshot_sequence > 0);
    assert_eq!(second.snapshot_sequence, first.snapshot_sequence + 1);
}

#[test]
fn telemetry_snapshot_sequence_is_unique_under_concurrent_rust_observers() {
    let metrics = Arc::new(Metrics::default());
    let barrier = Arc::new(Barrier::new(CONCURRENT_SNAPSHOT_COUNT));

    let handles = (0..CONCURRENT_SNAPSHOT_COUNT)
        .map(|_thread_index| {
            let metrics = Arc::clone(&metrics);
            let barrier = Arc::clone(&barrier);
            thread::spawn(move || {
                barrier.wait();
                metrics.next_telemetry_snapshot_metadata()
            })
        })
        .collect::<Vec<_>>();
    let mut snapshots = handles
        .into_iter()
        .map(|handle| handle.join().expect("snapshot observer thread panicked"))
        .collect::<Vec<_>>();
    snapshots.sort_by_key(|snapshot| snapshot.snapshot_sequence);
    let sequences = snapshots
        .iter()
        .map(|snapshot| snapshot.snapshot_sequence)
        .collect::<Vec<_>>();
    let expected_sequences = (1..=CONCURRENT_SNAPSHOT_COUNT)
        .map(|sequence| u64::try_from(sequence).expect("concurrent snapshot count fits u64"))
        .collect::<Vec<_>>();

    assert_eq!(sequences, expected_sequences);
    assert!(snapshots
        .iter()
        .all(|snapshot| snapshot.schema_version == TELEMETRY_SNAPSHOT_SCHEMA_VERSION));
}

#[test]
fn telemetry_snapshot_sequence_saturates_at_u64_max() {
    let metrics = Metrics::default();
    metrics
        .telemetry_snapshot_sequence
        .store(u64::MAX - 1, Ordering::Relaxed);

    let first = metrics.next_telemetry_snapshot_metadata();
    let second = metrics.next_telemetry_snapshot_metadata();

    assert_eq!(first.snapshot_sequence, u64::MAX);
    assert_eq!(second.snapshot_sequence, u64::MAX);
    assert_eq!(first.schema_version, TELEMETRY_SNAPSHOT_SCHEMA_VERSION);
    assert_eq!(second.schema_version, TELEMETRY_SNAPSHOT_SCHEMA_VERSION);
}

#[test]
fn response_body_lifecycle_metrics_track_outcomes() {
    let metrics = Metrics::default();

    metrics.response_body_finished(ResponseBodyLifecycleOutcome::ReuseEligible);
    metrics.response_body_finished(ResponseBodyLifecycleOutcome::Closed);
    metrics.response_body_finished(ResponseBodyLifecycleOutcome::Aborted);

    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.response_body_reuse_eligible, 1);
    assert_eq!(snapshot.response_body_closed, 1);
    assert_eq!(snapshot.response_body_aborted, 1);
}

#[test]
fn connection_lifecycle_metrics_track_current_and_historical_counts() {
    let metrics = Metrics::default();

    metrics.connection_opened();
    metrics.connection_became_idle();
    metrics.connection_reused();
    metrics.connection_left_idle();
    metrics.connection_aborted();
    metrics.connection_closed();
    metrics.connection_open_failed();
    metrics.idle_timeout_eviction();

    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.active_connections, 0);
    assert_eq!(snapshot.idle_connections, 0);
    assert_eq!(snapshot.connections_opened, 1);
    assert_eq!(snapshot.connections_open_failed, 1);
    assert_eq!(snapshot.connections_closed, 1);
    assert_eq!(snapshot.connections_reused, 1);
    assert_eq!(snapshot.connections_aborted, 1);
    assert_eq!(snapshot.idle_timeout_evictions, 1);
}

#[test]
fn transport_state_coherence_rejects_mismatched_acquire_pressure() {
    let metrics = Metrics::default();

    let origin_metrics = metrics.origin_metrics("https://api.example.com");
    metrics.pool_acquire_started();
    origin_metrics.pool_acquire_started();
    metrics.pool_acquire_waited();

    let snapshot = metrics.transport_state_snapshot_once(test_metadata());

    assert!(!snapshot.has_coherent_pressure());
}

#[test]
fn transport_state_coherence_rejects_mismatched_connection_lifecycle() {
    let metrics = Metrics::default();

    let origin_metrics = metrics.origin_metrics("https://api.example.com");
    metrics.connection_opened();
    origin_metrics.connection_opened();
    metrics.idle_timeout_eviction();

    let snapshot = metrics.transport_state_snapshot_once(test_metadata());

    assert!(!snapshot.has_coherent_pressure());
}

#[test]
fn transport_state_coherence_accepts_incomplete_historical_origin_pressure() {
    let metrics = Metrics::default();

    metrics.active_request_started();
    metrics.pool_acquire_started();
    let origin_metrics = metrics.origin_metrics("https://api.example.com");
    origin_metrics.active_request_started();
    let snapshot = TransportStateSnapshot {
        metadata: test_metadata(),
        metrics: metrics.snapshot(),
        origins: metrics.origin_snapshots(),
        origins_include_all_historical_pressure: false,
    };

    assert!(snapshot.has_coherent_pressure());
}

fn test_metadata() -> TelemetrySnapshotMetadata {
    TelemetrySnapshotMetadata {
        schema_version: TELEMETRY_SNAPSHOT_SCHEMA_VERSION,
        snapshot_sequence: 1,
    }
}
