use super::AcquireGate;
use crate::core::metrics::Metrics;
use pyo3::Python;
use std::sync::Arc;
use std::sync::Once;
use std::thread;
use std::time::Duration;
use tokio::runtime::Builder;

const ORIGIN: &str = "http://example.com";
const SECONDARY_ORIGIN: &str = "http://api.example.com";

fn initialize_python() {
    static PYTHON: Once = Once::new();
    PYTHON.call_once(Python::initialize);
}

fn test_runtime() -> tokio::runtime::Runtime {
    Builder::new_current_thread().enable_time().build().unwrap()
}

fn find_origin_snapshot(
    metrics: &Metrics,
    origin: &str,
) -> crate::core::metrics::OriginMetricsSnapshot {
    metrics
        .origin_snapshots()
        .into_iter()
        .find(|snapshot| snapshot.origin == origin)
        .unwrap()
}

#[test]
fn available_permit_does_not_use_pending_queue() {
    let metrics = Arc::new(Metrics::default());
    let gate = AcquireGate::new(1, None, 0, Arc::clone(&metrics));
    let runtime = test_runtime();

    let permit = runtime.block_on(gate.acquire(ORIGIN, 0.1)).unwrap();
    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.active_requests, 1);
    assert_eq!(snapshot.pending_requests, 0);
    assert_eq!(snapshot.peak_pending_requests, 0);
    assert_eq!(snapshot.pool_acquire_attempts, 1);
    assert_eq!(snapshot.pool_acquire_immediate, 1);
    assert_eq!(snapshot.pool_acquire_waited, 0);
    assert_eq!(snapshot.pool_acquire_timeouts, 0);
    assert_eq!(snapshot.pool_acquire_wait_time_total_ns, 0);
    let origin_snapshot = find_origin_snapshot(&metrics, ORIGIN);
    assert_eq!(origin_snapshot.active_requests, 1);
    assert_eq!(origin_snapshot.pending_requests, 0);
    assert_eq!(origin_snapshot.peak_pending_requests, 0);
    assert_eq!(origin_snapshot.pool_acquire_attempts, 1);
    assert_eq!(origin_snapshot.pool_acquire_immediate, 1);
    assert_eq!(origin_snapshot.pool_acquire_waited, 0);
    let activity_before_drop = origin_snapshot.last_activity_at_ns;

    thread::sleep(Duration::from_millis(1));
    drop(permit);
    assert_eq!(metrics.snapshot().active_requests, 0);
    let origin_snapshot = find_origin_snapshot(&metrics, ORIGIN);
    assert_eq!(origin_snapshot.active_requests, 0);
    assert!(origin_snapshot.last_activity_at_ns > activity_before_drop);
}

#[test]
fn acquire_permit_releases_capacity_on_drop() {
    let metrics = Arc::new(Metrics::default());
    let gate = AcquireGate::new(1, None, 0, Arc::clone(&metrics));
    let runtime = test_runtime();

    let permit = runtime.block_on(gate.acquire(ORIGIN, 0.1)).unwrap();
    assert_eq!(metrics.snapshot().active_requests, 1);
    drop(permit);
    assert_eq!(metrics.snapshot().active_requests, 0);

    let permit = runtime.block_on(gate.acquire(ORIGIN, 0.1)).unwrap();
    assert_eq!(metrics.snapshot().active_requests, 1);
    drop(permit);

    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.active_requests, 0);
    assert_eq!(snapshot.pending_requests, 0);
    assert_eq!(snapshot.pool_acquire_timeouts, 0);
}

#[test]
fn queue_full_updates_pool_timeout_without_pending_leak() {
    initialize_python();

    let metrics = Arc::new(Metrics::default());
    let gate = AcquireGate::new(0, None, 0, Arc::clone(&metrics));
    let runtime = test_runtime();

    let error = match runtime.block_on(gate.acquire(ORIGIN, 0.1)) {
        Ok(_permit) => panic!("acquire unexpectedly succeeded"),
        Err(err) => err,
    };

    assert!(error.to_string().contains("request acquire queue is full"));
    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.pending_requests, 0);
    assert_eq!(snapshot.peak_pending_requests, 0);
    assert_eq!(snapshot.pool_acquire_attempts, 1);
    assert_eq!(snapshot.pool_acquire_immediate, 0);
    assert_eq!(snapshot.pool_acquire_waited, 0);
    assert_eq!(snapshot.pool_acquire_timeouts, 1);
    assert_eq!(snapshot.pool_acquire_wait_time_total_ns, 0);
    let origin_snapshot = find_origin_snapshot(&metrics, ORIGIN);
    assert_eq!(origin_snapshot.pending_requests, 0);
    assert_eq!(origin_snapshot.peak_pending_requests, 0);
    assert_eq!(origin_snapshot.pool_acquire_attempts, 1);
    assert_eq!(origin_snapshot.pool_acquire_timeouts, 1);
}

#[test]
fn acquire_timeout_updates_pool_timeout_without_pending_leak() {
    initialize_python();

    let metrics = Arc::new(Metrics::default());
    let gate = AcquireGate::new(0, None, 1, Arc::clone(&metrics));
    let runtime = test_runtime();

    let error = match runtime.block_on(gate.acquire(ORIGIN, 0.001)) {
        Ok(_permit) => panic!("acquire unexpectedly succeeded"),
        Err(err) => err,
    };

    assert!(error
        .to_string()
        .contains("request acquire timeout expired"));
    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.pending_requests, 0);
    assert_eq!(snapshot.peak_pending_requests, 1);
    assert_eq!(snapshot.pool_acquire_attempts, 1);
    assert_eq!(snapshot.pool_acquire_immediate, 0);
    assert_eq!(snapshot.pool_acquire_waited, 1);
    assert_eq!(snapshot.pool_acquire_timeouts, 1);
    assert!(snapshot.pool_acquire_wait_time_last_ns > 0);
    assert!(snapshot.pool_acquire_wait_time_max_ns >= snapshot.pool_acquire_wait_time_last_ns);
    assert!(snapshot.pool_acquire_wait_time_total_ns >= snapshot.pool_acquire_wait_time_last_ns);
    let origin_snapshot = find_origin_snapshot(&metrics, ORIGIN);
    assert_eq!(origin_snapshot.pending_requests, 0);
    assert_eq!(origin_snapshot.peak_pending_requests, 1);
    assert_eq!(origin_snapshot.pool_acquire_attempts, 1);
    assert_eq!(origin_snapshot.pool_acquire_waited, 1);
    assert_eq!(origin_snapshot.pool_acquire_timeouts, 1);
    assert!(origin_snapshot.pool_acquire_wait_time_last_ns > 0);
}

#[test]
fn dropped_waiting_acquire_releases_pending_slot() {
    let metrics = Arc::new(Metrics::default());
    let gate = AcquireGate::new(0, None, 1, Arc::clone(&metrics));
    let runtime = test_runtime();

    runtime.block_on(async {
        {
            let acquire = gate.acquire(ORIGIN, 60.0);
            tokio::pin!(acquire);

            let result = tokio::time::timeout(Duration::from_millis(1), &mut acquire).await;
            assert!(result.is_err());
            let snapshot = metrics.snapshot();
            assert_eq!(snapshot.active_requests, 0);
            assert_eq!(snapshot.pending_requests, 1);
            assert_eq!(snapshot.peak_pending_requests, 1);
            assert_eq!(snapshot.pool_acquire_attempts, 1);
            assert_eq!(snapshot.pool_acquire_immediate, 0);
            assert_eq!(snapshot.pool_acquire_waited, 1);
            assert_eq!(snapshot.pool_acquire_wait_time_last_ns, 0);
            let origin_snapshot = find_origin_snapshot(&metrics, ORIGIN);
            assert_eq!(origin_snapshot.active_requests, 0);
            assert_eq!(origin_snapshot.pending_requests, 1);
            assert_eq!(origin_snapshot.peak_pending_requests, 1);
            assert_eq!(origin_snapshot.pool_acquire_wait_time_last_ns, 0);
        }

        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.active_requests, 0);
        assert_eq!(snapshot.pending_requests, 0);
        assert_eq!(snapshot.pool_acquire_timeouts, 0);
        assert!(snapshot.pool_acquire_wait_time_last_ns > 0);
        assert!(
            snapshot.pool_acquire_wait_time_total_ns >= snapshot.pool_acquire_wait_time_last_ns
        );
        let origin_snapshot = find_origin_snapshot(&metrics, ORIGIN);
        assert_eq!(origin_snapshot.pending_requests, 0);
        assert!(origin_snapshot.pool_acquire_wait_time_last_ns > 0);
    });
}

#[test]
fn same_origin_limit_tracks_pending_without_active_leak() {
    let metrics = Arc::new(Metrics::default());
    let gate = AcquireGate::new(2, Some(1), 1, Arc::clone(&metrics));
    let runtime = test_runtime();

    runtime.block_on(async {
        let permit = gate.acquire(ORIGIN, 0.1).await.unwrap();
        assert_eq!(metrics.snapshot().active_requests, 1);

        {
            let acquire = gate.acquire(ORIGIN, 60.0);
            tokio::pin!(acquire);

            let result = tokio::time::timeout(Duration::from_millis(1), &mut acquire).await;
            assert!(result.is_err());
            let snapshot = metrics.snapshot();
            assert_eq!(snapshot.active_requests, 1);
            assert_eq!(snapshot.pending_requests, 1);
            assert_eq!(snapshot.peak_pending_requests, 1);
            assert_eq!(snapshot.pool_acquire_attempts, 2);
            assert_eq!(snapshot.pool_acquire_immediate, 1);
            assert_eq!(snapshot.pool_acquire_waited, 1);
            let origin_snapshot = find_origin_snapshot(&metrics, ORIGIN);
            assert_eq!(origin_snapshot.active_requests, 1);
            assert_eq!(origin_snapshot.pending_requests, 1);
            assert_eq!(origin_snapshot.pool_acquire_attempts, 2);
            assert_eq!(origin_snapshot.pool_acquire_immediate, 1);
            assert_eq!(origin_snapshot.pool_acquire_waited, 1);
        }

        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.active_requests, 1);
        assert_eq!(snapshot.pending_requests, 0);
        assert!(snapshot.pool_acquire_wait_time_last_ns > 0);
        let origin_snapshot = find_origin_snapshot(&metrics, ORIGIN);
        assert_eq!(origin_snapshot.active_requests, 1);
        assert_eq!(origin_snapshot.pending_requests, 0);
        drop(permit);
        assert_eq!(metrics.snapshot().active_requests, 0);
        assert_eq!(find_origin_snapshot(&metrics, ORIGIN).active_requests, 0);
    });
}

#[test]
fn different_origins_do_not_share_origin_limit() {
    let metrics = Arc::new(Metrics::default());
    let gate = AcquireGate::new(2, Some(1), 0, Arc::clone(&metrics));
    let runtime = test_runtime();

    runtime.block_on(async {
        let first = gate.acquire(ORIGIN, 0.1).await.unwrap();
        let second = gate.acquire(SECONDARY_ORIGIN, 0.1).await.unwrap();

        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.active_requests, 2);
        assert_eq!(snapshot.pending_requests, 0);
        let origin_snapshot = find_origin_snapshot(&metrics, ORIGIN);
        let secondary_origin_snapshot = find_origin_snapshot(&metrics, SECONDARY_ORIGIN);
        assert_eq!(origin_snapshot.active_requests, 1);
        assert_eq!(secondary_origin_snapshot.active_requests, 1);
        assert_eq!(origin_snapshot.pool_acquire_attempts, 1);
        assert_eq!(secondary_origin_snapshot.pool_acquire_attempts, 1);

        drop(first);
        drop(second);
        assert_eq!(metrics.snapshot().active_requests, 0);
        assert_eq!(find_origin_snapshot(&metrics, ORIGIN).active_requests, 0);
        assert_eq!(
            find_origin_snapshot(&metrics, SECONDARY_ORIGIN).active_requests,
            0
        );
    });
}

#[test]
fn origin_queue_full_updates_pool_timeout_without_active_leak() {
    initialize_python();

    let metrics = Arc::new(Metrics::default());
    let gate = AcquireGate::new(10, Some(0), 0, Arc::clone(&metrics));
    let runtime = test_runtime();

    let error = match runtime.block_on(gate.acquire(ORIGIN, 0.1)) {
        Ok(_permit) => panic!("acquire unexpectedly succeeded"),
        Err(err) => err,
    };

    assert!(error.to_string().contains("request acquire queue is full"));
    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.active_requests, 0);
    assert_eq!(snapshot.pending_requests, 0);
    assert_eq!(snapshot.pool_acquire_timeouts, 1);
    let origin_snapshot = find_origin_snapshot(&metrics, ORIGIN);
    assert_eq!(origin_snapshot.active_requests, 0);
    assert_eq!(origin_snapshot.pending_requests, 0);
    assert_eq!(origin_snapshot.pool_acquire_attempts, 1);
    assert_eq!(origin_snapshot.pool_acquire_timeouts, 1);
}

#[test]
fn dropped_waiting_global_acquire_releases_origin_slot() {
    let metrics = Arc::new(Metrics::default());
    let gate = AcquireGate::new(1, Some(1), 1, Arc::clone(&metrics));
    let runtime = test_runtime();

    runtime.block_on(async {
        let global_blocker = gate.acquire(SECONDARY_ORIGIN, 0.1).await.unwrap();

        {
            let acquire = gate.acquire(ORIGIN, 60.0);
            tokio::pin!(acquire);

            let result = tokio::time::timeout(Duration::from_millis(1), &mut acquire).await;
            assert!(result.is_err());
            let snapshot = metrics.snapshot();
            assert_eq!(snapshot.active_requests, 1);
            assert_eq!(snapshot.pending_requests, 1);
            let origin_snapshot = find_origin_snapshot(&metrics, ORIGIN);
            assert_eq!(origin_snapshot.active_requests, 0);
            assert_eq!(origin_snapshot.pending_requests, 1);
        }

        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.active_requests, 1);
        assert_eq!(snapshot.pending_requests, 0);
        assert_eq!(find_origin_snapshot(&metrics, ORIGIN).pending_requests, 0);
        drop(global_blocker);

        let permit = gate.acquire(ORIGIN, 0.1).await.unwrap();
        assert_eq!(metrics.snapshot().active_requests, 1);
        drop(permit);
        assert_eq!(metrics.snapshot().active_requests, 0);
    });
}
