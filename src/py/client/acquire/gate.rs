use super::diagnostics::PoolDiagnosticsSnapshot;
use super::origin::OriginGates;
use super::pending::{AcquiredPermits, ImmediateAcquire, PendingQueue};
use super::permit::AcquirePermit;
use super::telemetry::AcquireTelemetry;
use crate::core::metrics::{Metrics, OriginMetrics, PendingRequestBlockingReason};
use crate::messages::{POOL_ACQUIRE_QUEUE_FULL, POOL_ACQUIRE_TIMEOUT};
use crate::py::client::timeout_diagnostics::{
    pool_timeout_error, remaining_duration, TimeoutContext, TimeoutPhase,
};
use pyo3::prelude::*;
use std::sync::Arc;
use std::time::Instant;
use tokio::sync::Semaphore;

#[derive(Clone)]
pub struct AcquireGate {
    global_semaphore: Arc<Semaphore>,
    max_active_requests: usize,
    max_active_requests_per_origin: Option<usize>,
    max_pending_requests: usize,
    metrics: Arc<Metrics>,
    origin_gates: Option<OriginGates>,
    pending_queue: Arc<PendingQueue>,
}

impl AcquireGate {
    pub fn new(
        max_active_requests: usize,
        max_active_requests_per_origin: Option<usize>,
        max_pending_requests: usize,
        metrics: Arc<Metrics>,
    ) -> Self {
        Self {
            global_semaphore: Arc::new(Semaphore::new(max_active_requests)),
            max_active_requests,
            max_active_requests_per_origin,
            max_pending_requests,
            metrics,
            origin_gates: max_active_requests_per_origin.map(OriginGates::new),
            pending_queue: Arc::new(PendingQueue::default()),
        }
    }

    pub async fn acquire(
        &self,
        origin: &str,
        pool_timeout: f64,
        redirect_hop: usize,
    ) -> PyResult<AcquirePermit> {
        let started = Instant::now();
        let timeout_context = TimeoutContext::new(
            TimeoutPhase::PoolAcquire,
            started,
            pool_timeout,
            origin,
            redirect_hop,
        );
        let origin_metrics = self.metrics.origin_metrics(origin);
        let mut telemetry =
            AcquireTelemetry::start(Arc::clone(&self.metrics), Arc::clone(&origin_metrics));
        let origin_semaphore = self.origin_semaphore(origin);
        let queue_was_empty = match self
            .pending_queue
            .try_acquire_immediate(Arc::clone(&self.global_semaphore), origin_semaphore.clone())?
        {
            ImmediateAcquire::Acquired(permits) => {
                telemetry.finish_success();
                return Ok(self.acquire_permit_from(permits, origin_metrics));
            }
            ImmediateAcquire::Queue { queue_was_empty } => queue_was_empty,
        };

        let timeout = remaining_duration("Timeouts.pool", &timeout_context)?;
        let blocked_by = self.pending_blocking_reason(queue_was_empty, origin_semaphore.as_ref());
        let mut waiter = self
            .pending_queue
            .try_register(
                Arc::clone(&self.metrics),
                Arc::clone(&origin_metrics),
                self.max_pending_requests,
                blocked_by,
            )
            .map_err(|_err| pool_timeout_error(&timeout_context, POOL_ACQUIRE_QUEUE_FULL))?;
        telemetry.mark_waited();
        let acquire_result = tokio::time::timeout(
            timeout,
            waiter.acquire_permits(Arc::clone(&self.global_semaphore), origin_semaphore),
        )
        .await;

        match acquire_result {
            Ok(Ok(permits)) => {
                drop(waiter);
                Ok(self.acquire_permit_from(permits, origin_metrics))
            }
            Ok(Err(err)) => {
                drop(waiter);
                Err(err)
            }
            Err(_elapsed) => {
                drop(waiter);
                self.metrics.pool_acquire_timeout();
                origin_metrics.pool_acquire_timeout();
                Err(pool_timeout_error(&timeout_context, POOL_ACQUIRE_TIMEOUT))
            }
        }
    }

    fn origin_semaphore(&self, origin: &str) -> Option<Arc<Semaphore>> {
        self.origin_gates
            .as_ref()
            .map(|origin_gates| origin_gates.semaphore(origin))
    }

    fn pending_blocking_reason(
        &self,
        queue_was_empty: bool,
        origin_semaphore: Option<&Arc<Semaphore>>,
    ) -> PendingRequestBlockingReason {
        let global_blocked = self.global_semaphore.available_permits() == 0;
        let origin_blocked =
            origin_semaphore.is_some_and(|semaphore| semaphore.available_permits() == 0);

        match (queue_was_empty, global_blocked, origin_blocked) {
            (false, false, false) => PendingRequestBlockingReason::PendingQueueOrder,
            (false, _, _) | (true, false, false) | (true, true, true) => {
                PendingRequestBlockingReason::Mixed
            }
            (true, true, false) => PendingRequestBlockingReason::GlobalActiveRequests,
            (true, false, true) => PendingRequestBlockingReason::PerOriginActiveRequests,
        }
    }

    fn acquire_permit_from(
        &self,
        permits: AcquiredPermits,
        origin_metrics: Arc<OriginMetrics>,
    ) -> AcquirePermit {
        AcquirePermit::new(
            permits.global,
            permits.origin,
            Arc::clone(&self.metrics),
            origin_metrics,
            Arc::clone(&self.pending_queue),
        )
    }

    pub fn diagnostics(&self) -> PoolDiagnosticsSnapshot {
        let metadata = self.metrics.next_telemetry_snapshot_metadata();
        let metrics = self.metrics.snapshot();
        PoolDiagnosticsSnapshot::new(
            metadata,
            &metrics,
            self.metrics.origin_pool_diagnostics_snapshots(),
            self.max_active_requests,
            self.max_active_requests_per_origin,
            self.max_pending_requests,
        )
    }
}
