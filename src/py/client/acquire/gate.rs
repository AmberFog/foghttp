use super::diagnostics::PoolDiagnosticsSnapshot;
use super::origin::OriginGates;
use super::pending::PendingAcquire;
use super::permit::AcquirePermit;
use super::telemetry::AcquireTelemetry;
use crate::core::metrics::{Metrics, OriginMetrics, PendingRequestBlockingReason};
use crate::errors::FogHttpError;
use crate::messages::{POOL_ACQUIRE_QUEUE_FULL, POOL_ACQUIRE_TIMEOUT};
use crate::py::client::timeout_diagnostics::{
    pool_timeout_error, remaining_duration, TimeoutContext, TimeoutPhase,
};
use pyo3::prelude::*;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::{OwnedSemaphorePermit, Semaphore, TryAcquireError};

#[derive(Clone)]
pub struct AcquireGate {
    global_semaphore: Arc<Semaphore>,
    max_active_requests: usize,
    max_active_requests_per_origin: Option<usize>,
    max_pending_requests: usize,
    metrics: Arc<Metrics>,
    origin_gates: Option<OriginGates>,
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
        let origin_permit = self
            .acquire_origin_permit(
                origin,
                &timeout_context,
                &mut telemetry,
                Arc::clone(&origin_metrics),
            )
            .await?;
        let global_permit = self
            .acquire_semaphore(
                Arc::clone(&self.global_semaphore),
                remaining_duration("Timeouts.pool", &timeout_context)?,
                &mut telemetry,
                Arc::clone(&origin_metrics),
                &timeout_context,
                PendingRequestBlockingReason::GlobalActiveRequests,
            )
            .await?;
        telemetry.finish_success();

        Ok(AcquirePermit::new(
            global_permit,
            origin_permit,
            Arc::clone(&self.metrics),
            origin_metrics,
        ))
    }

    async fn acquire_origin_permit(
        &self,
        origin: &str,
        timeout_context: &TimeoutContext<'_>,
        telemetry: &mut AcquireTelemetry,
        origin_metrics: Arc<OriginMetrics>,
    ) -> PyResult<Option<OwnedSemaphorePermit>> {
        let Some(origin_gates) = &self.origin_gates else {
            return Ok(None);
        };

        let semaphore = origin_gates.semaphore(origin);
        self.acquire_semaphore(
            semaphore,
            remaining_duration("Timeouts.pool", timeout_context)?,
            telemetry,
            origin_metrics,
            timeout_context,
            PendingRequestBlockingReason::PerOriginActiveRequests,
        )
        .await
        .map(Some)
    }

    async fn acquire_semaphore(
        &self,
        semaphore: Arc<Semaphore>,
        timeout: Duration,
        telemetry: &mut AcquireTelemetry,
        origin_metrics: Arc<OriginMetrics>,
        timeout_context: &TimeoutContext<'_>,
        blocked_by: PendingRequestBlockingReason,
    ) -> PyResult<OwnedSemaphorePermit> {
        match Arc::clone(&semaphore).try_acquire_owned() {
            Ok(permit) => {
                return Ok(permit);
            }
            Err(TryAcquireError::NoPermits) => {}
            Err(TryAcquireError::Closed) => {
                return Err(FogHttpError::new_err("acquire gate is closed"));
            }
        }

        let pending = PendingAcquire::try_start(
            Arc::clone(&self.metrics),
            Arc::clone(&origin_metrics),
            self.max_pending_requests,
            blocked_by,
        )
        .map_err(|_err| pool_timeout_error(timeout_context, POOL_ACQUIRE_QUEUE_FULL))?;
        telemetry.mark_waited();
        let acquire_result = tokio::time::timeout(timeout, semaphore.acquire_owned()).await;
        drop(pending);

        match acquire_result {
            Ok(Ok(permit)) => Ok(permit),
            Ok(Err(err)) => Err(FogHttpError::new_err(err.to_string())),
            Err(_elapsed) => {
                self.metrics.pool_acquire_timeout();
                origin_metrics.pool_acquire_timeout();
                Err(pool_timeout_error(timeout_context, POOL_ACQUIRE_TIMEOUT))
            }
        }
    }

    pub fn diagnostics(&self) -> PoolDiagnosticsSnapshot {
        let metrics = self.metrics.snapshot();
        PoolDiagnosticsSnapshot::new(
            &metrics,
            self.metrics.origin_pool_diagnostics_snapshots(),
            self.max_active_requests,
            self.max_active_requests_per_origin,
            self.max_pending_requests,
        )
    }
}
