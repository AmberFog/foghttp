use super::AcquireGate;
use crate::core::metrics::{
    Metrics, MetricsSnapshot, OriginMetricsSnapshot, PendingRequestBlockingReason,
};
use pyo3::Python;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::Once;
use std::task::{Context, Poll, Wake, Waker};
use std::thread;
use std::time::Duration;
use tokio::runtime::Builder;

const ORIGIN: &str = "http://example.com";
const SECONDARY_ORIGIN: &str = "http://api.example.com";
const ACQUIRE_READY_TIMEOUT: Duration = Duration::from_secs(1);

struct NoopWake;

impl Wake for NoopWake {
    fn wake(self: Arc<Self>) {}
}

fn initialize_python() {
    static PYTHON: Once = Once::new();
    PYTHON.call_once(Python::initialize);
}

fn test_runtime() -> tokio::runtime::Runtime {
    Builder::new_current_thread().enable_time().build().unwrap()
}

fn find_origin_snapshot(metrics: &Metrics, origin: &str) -> OriginMetricsSnapshot {
    metrics
        .origin_snapshots()
        .into_iter()
        .find(|snapshot| snapshot.origin == origin)
        .unwrap()
}

fn find_origin_diagnostics(
    gate: &AcquireGate,
    origin: &str,
) -> crate::core::metrics::OriginPoolDiagnosticsSnapshot {
    gate.diagnostics()
        .origins
        .into_iter()
        .find(|snapshot| snapshot.origin == origin)
        .unwrap()
}

fn assert_acquire_waits<F, T>(mut future: Pin<&mut F>)
where
    F: Future<Output = T>,
{
    let waker = Waker::from(Arc::new(NoopWake));
    let mut context = Context::from_waker(&waker);
    assert!(matches!(future.as_mut().poll(&mut context), Poll::Pending));
}

async fn acquire_before_deadline<F, T>(future: Pin<&mut F>) -> T
where
    F: Future<Output = T>,
{
    tokio::time::timeout(ACQUIRE_READY_TIMEOUT, future)
        .await
        .expect("acquire did not complete before deadline")
}

fn assert_request_pressure(metrics: &Metrics, active: usize, pending: usize) -> MetricsSnapshot {
    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.active_requests, active);
    assert_eq!(snapshot.pending_requests, pending);
    snapshot
}

fn assert_origin_pressure(
    metrics: &Metrics,
    origin: &str,
    active: usize,
    pending: usize,
) -> OriginMetricsSnapshot {
    let snapshot = find_origin_snapshot(metrics, origin);
    assert_eq!(snapshot.active_requests, active);
    assert_eq!(snapshot.pending_requests, pending);
    snapshot
}

#[test]
fn available_permit_does_not_use_pending_queue() {
    let metrics = Arc::new(Metrics::default());
    let gate = AcquireGate::new(1, None, 0, Arc::clone(&metrics));
    let runtime = test_runtime();

    let permit = runtime.block_on(gate.acquire(ORIGIN, 0.1, 0)).unwrap();
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

    let permit = runtime.block_on(gate.acquire(ORIGIN, 0.1, 0)).unwrap();
    assert_eq!(metrics.snapshot().active_requests, 1);
    drop(permit);
    assert_eq!(metrics.snapshot().active_requests, 0);

    let permit = runtime.block_on(gate.acquire(ORIGIN, 0.1, 0)).unwrap();
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

    let error = match runtime.block_on(gate.acquire(ORIGIN, 0.1, 0)) {
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

    let error = match runtime.block_on(gate.acquire(ORIGIN, 0.001, 0)) {
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
            let acquire = gate.acquire(ORIGIN, 60.0, 0);
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
        let permit = gate.acquire(ORIGIN, 0.1, 0).await.unwrap();
        assert_eq!(metrics.snapshot().active_requests, 1);

        {
            let acquire = gate.acquire(ORIGIN, 60.0, 0);
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
        let first = gate.acquire(ORIGIN, 0.1, 0).await.unwrap();
        let second = gate.acquire(SECONDARY_ORIGIN, 0.1, 0).await.unwrap();

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

    let error = match runtime.block_on(gate.acquire(ORIGIN, 0.1, 0)) {
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
        let global_blocker = gate.acquire(SECONDARY_ORIGIN, 0.1, 0).await.unwrap();

        {
            let acquire = gate.acquire(ORIGIN, 60.0, 0);
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

        let permit = gate.acquire(ORIGIN, 0.1, 0).await.unwrap();
        assert_eq!(metrics.snapshot().active_requests, 1);
        drop(permit);
        assert_eq!(metrics.snapshot().active_requests, 0);
    });
}

#[test]
fn global_limit_wakes_waiters_fifo_across_origins() {
    let metrics = Arc::new(Metrics::default());
    let gate = AcquireGate::new(1, None, 2, Arc::clone(&metrics));
    let runtime = test_runtime();

    runtime.block_on(async {
        let blocker = gate.acquire(ORIGIN, 0.1, 0).await.unwrap();

        let first_waiter = gate.acquire(SECONDARY_ORIGIN, 60.0, 0);
        tokio::pin!(first_waiter);
        assert_acquire_waits(first_waiter.as_mut());

        let second_waiter = gate.acquire(ORIGIN, 60.0, 0);
        tokio::pin!(second_waiter);
        assert_acquire_waits(second_waiter.as_mut());

        let snapshot = assert_request_pressure(&metrics, 1, 2);
        assert_eq!(snapshot.peak_pending_requests, 2);
        assert_origin_pressure(&metrics, ORIGIN, 1, 1);
        assert_origin_pressure(&metrics, SECONDARY_ORIGIN, 0, 1);

        drop(blocker);

        let first_permit = acquire_before_deadline(first_waiter.as_mut())
            .await
            .unwrap();
        assert_request_pressure(&metrics, 1, 1);
        assert_origin_pressure(&metrics, ORIGIN, 0, 1);
        assert_origin_pressure(&metrics, SECONDARY_ORIGIN, 1, 0);

        drop(first_permit);

        let second_permit = acquire_before_deadline(second_waiter.as_mut())
            .await
            .unwrap();
        assert_request_pressure(&metrics, 1, 0);
        assert_origin_pressure(&metrics, ORIGIN, 1, 0);

        drop(second_permit);
        assert_request_pressure(&metrics, 0, 0);
    });
}

#[test]
fn origin_limit_wakes_same_origin_waiters_fifo() {
    let metrics = Arc::new(Metrics::default());
    let gate = AcquireGate::new(2, Some(1), 2, Arc::clone(&metrics));
    let runtime = test_runtime();

    runtime.block_on(async {
        let blocker = gate.acquire(ORIGIN, 0.1, 0).await.unwrap();

        let first_waiter = gate.acquire(ORIGIN, 60.0, 0);
        tokio::pin!(first_waiter);
        assert_acquire_waits(first_waiter.as_mut());

        let second_waiter = gate.acquire(ORIGIN, 60.0, 0);
        tokio::pin!(second_waiter);
        assert_acquire_waits(second_waiter.as_mut());

        let snapshot = assert_request_pressure(&metrics, 1, 2);
        assert_eq!(snapshot.peak_pending_requests, 2);
        assert_origin_pressure(&metrics, ORIGIN, 1, 2);

        drop(blocker);

        let first_permit = acquire_before_deadline(first_waiter.as_mut())
            .await
            .unwrap();
        assert_request_pressure(&metrics, 1, 1);
        assert_origin_pressure(&metrics, ORIGIN, 1, 1);

        drop(first_permit);

        let second_permit = acquire_before_deadline(second_waiter.as_mut())
            .await
            .unwrap();
        assert_request_pressure(&metrics, 1, 0);
        assert_origin_pressure(&metrics, ORIGIN, 1, 0);

        drop(second_permit);
        assert_request_pressure(&metrics, 0, 0);
    });
}

#[test]
fn origin_then_global_order_preserves_same_origin_queue_position() {
    let metrics = Arc::new(Metrics::default());
    let gate = AcquireGate::new(1, Some(1), 2, Arc::clone(&metrics));
    let runtime = test_runtime();

    runtime.block_on(async {
        let global_blocker = gate.acquire(SECONDARY_ORIGIN, 0.1, 0).await.unwrap();

        let first_origin_waiter = gate.acquire(ORIGIN, 60.0, 0);
        tokio::pin!(first_origin_waiter);
        assert_acquire_waits(first_origin_waiter.as_mut());

        let diagnostics = find_origin_diagnostics(&gate, ORIGIN);
        assert_eq!(
            diagnostics.blocked_by,
            PendingRequestBlockingReason::GlobalActiveRequests
        );
        assert_eq!(diagnostics.active_requests, 0);
        assert_eq!(diagnostics.pending_requests, 1);

        let second_origin_waiter = gate.acquire(ORIGIN, 60.0, 0);
        tokio::pin!(second_origin_waiter);
        assert_acquire_waits(second_origin_waiter.as_mut());

        let snapshot = assert_request_pressure(&metrics, 1, 2);
        assert_eq!(snapshot.peak_pending_requests, 2);
        let diagnostics = find_origin_diagnostics(&gate, ORIGIN);
        assert_eq!(diagnostics.blocked_by, PendingRequestBlockingReason::Mixed);
        assert_eq!(diagnostics.active_requests, 0);
        assert_eq!(diagnostics.pending_requests, 2);

        drop(global_blocker);

        let first_permit = acquire_before_deadline(first_origin_waiter.as_mut())
            .await
            .unwrap();
        assert_request_pressure(&metrics, 1, 1);
        assert_origin_pressure(&metrics, ORIGIN, 1, 1);

        drop(first_permit);

        let second_permit = acquire_before_deadline(second_origin_waiter.as_mut())
            .await
            .unwrap();
        assert_request_pressure(&metrics, 1, 0);
        assert_origin_pressure(&metrics, ORIGIN, 1, 0);

        drop(second_permit);
        assert_request_pressure(&metrics, 0, 0);
        assert_origin_pressure(&metrics, ORIGIN, 0, 0);
    });
}

#[test]
fn global_wait_timeout_releases_origin_slot() {
    initialize_python();

    let metrics = Arc::new(Metrics::default());
    let gate = AcquireGate::new(1, Some(1), 2, Arc::clone(&metrics));
    let runtime = test_runtime();

    runtime.block_on(async {
        let global_blocker = gate.acquire(SECONDARY_ORIGIN, 0.1, 0).await.unwrap();

        let error = match gate.acquire(ORIGIN, 0.001, 0).await {
            Ok(_permit) => panic!("acquire unexpectedly succeeded"),
            Err(err) => err,
        };
        assert!(error
            .to_string()
            .contains("request acquire timeout expired"));

        let snapshot = assert_request_pressure(&metrics, 1, 0);
        assert_eq!(snapshot.peak_pending_requests, 1);
        assert_eq!(snapshot.pool_acquire_timeouts, 1);
        let origin_snapshot = assert_origin_pressure(&metrics, ORIGIN, 0, 0);
        assert_eq!(origin_snapshot.peak_pending_requests, 1);
        assert_eq!(origin_snapshot.pool_acquire_timeouts, 1);

        drop(global_blocker);

        let permit = gate.acquire(ORIGIN, 0.1, 0).await.unwrap();
        assert_request_pressure(&metrics, 1, 0);
        assert_origin_pressure(&metrics, ORIGIN, 1, 0);

        drop(permit);
        assert_request_pressure(&metrics, 0, 0);
        assert_origin_pressure(&metrics, ORIGIN, 0, 0);
    });
}
