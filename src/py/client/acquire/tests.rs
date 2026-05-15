use super::AcquireGate;
use crate::core::metrics::Metrics;
use pyo3::Python;
use std::sync::Arc;
use std::sync::Once;
use std::time::Duration;
use tokio::runtime::Builder;

fn initialize_python() {
    static PYTHON: Once = Once::new();
    PYTHON.call_once(Python::initialize);
}

fn test_runtime() -> tokio::runtime::Runtime {
    Builder::new_current_thread().enable_time().build().unwrap()
}

#[test]
fn available_permit_does_not_use_pending_queue() {
    let metrics = Arc::new(Metrics::default());
    let gate = AcquireGate::new(1, 0, Arc::clone(&metrics));
    let runtime = test_runtime();

    let permit = runtime.block_on(gate.acquire(0.1)).unwrap();
    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.active_requests, 1);
    assert_eq!(snapshot.pending_requests, 0);
    assert_eq!(snapshot.pool_acquire_timeouts, 0);

    drop(permit);
    assert_eq!(metrics.snapshot().active_requests, 0);
}

#[test]
fn acquire_permit_releases_capacity_on_drop() {
    let metrics = Arc::new(Metrics::default());
    let gate = AcquireGate::new(1, 0, Arc::clone(&metrics));
    let runtime = test_runtime();

    let permit = runtime.block_on(gate.acquire(0.1)).unwrap();
    assert_eq!(metrics.snapshot().active_requests, 1);
    drop(permit);
    assert_eq!(metrics.snapshot().active_requests, 0);

    let permit = runtime.block_on(gate.acquire(0.1)).unwrap();
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
    let gate = AcquireGate::new(0, 0, Arc::clone(&metrics));
    let runtime = test_runtime();

    let error = match runtime.block_on(gate.acquire(0.1)) {
        Ok(_permit) => panic!("acquire unexpectedly succeeded"),
        Err(err) => err,
    };

    assert!(error.to_string().contains("request acquire queue is full"));
    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.pending_requests, 0);
    assert_eq!(snapshot.pool_acquire_timeouts, 1);
}

#[test]
fn acquire_timeout_updates_pool_timeout_without_pending_leak() {
    initialize_python();

    let metrics = Arc::new(Metrics::default());
    let gate = AcquireGate::new(0, 1, Arc::clone(&metrics));
    let runtime = test_runtime();

    let error = match runtime.block_on(gate.acquire(0.001)) {
        Ok(_permit) => panic!("acquire unexpectedly succeeded"),
        Err(err) => err,
    };

    assert!(error
        .to_string()
        .contains("request acquire timeout expired"));
    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.pending_requests, 0);
    assert_eq!(snapshot.pool_acquire_timeouts, 1);
}

#[test]
fn dropped_waiting_acquire_releases_pending_slot() {
    let metrics = Arc::new(Metrics::default());
    let gate = AcquireGate::new(0, 1, Arc::clone(&metrics));
    let runtime = test_runtime();

    runtime.block_on(async {
        {
            let acquire = gate.acquire(60.0);
            tokio::pin!(acquire);

            let result = tokio::time::timeout(Duration::from_millis(1), &mut acquire).await;
            assert!(result.is_err());
            let snapshot = metrics.snapshot();
            assert_eq!(snapshot.active_requests, 0);
            assert_eq!(snapshot.pending_requests, 1);
        }

        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.active_requests, 0);
        assert_eq!(snapshot.pending_requests, 0);
        assert_eq!(snapshot.pool_acquire_timeouts, 0);
    });
}
