use super::origin::OriginGates;
use super::pending::PendingAcquire;
use super::permit::AcquirePermit;
use crate::core::metrics::Metrics;
use crate::core::numeric;
use crate::errors::{FogHttpError, FogHttpPoolTimeoutError};
use crate::messages::POOL_ACQUIRE_TIMEOUT;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::{OwnedSemaphorePermit, Semaphore, TryAcquireError};

#[derive(Clone)]
pub struct AcquireGate {
    global_semaphore: Arc<Semaphore>,
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
            max_pending_requests,
            metrics,
            origin_gates: max_active_requests_per_origin.map(OriginGates::new),
        }
    }

    pub async fn acquire(&self, origin: &str, pool_timeout: f64) -> PyResult<AcquirePermit> {
        let started = Instant::now();
        let origin_permit = self
            .acquire_origin_permit(origin, pool_timeout, started)
            .await?;
        let global_permit = self
            .acquire_semaphore(
                Arc::clone(&self.global_semaphore),
                remaining_duration(pool_timeout, started)?,
            )
            .await?;

        Ok(AcquirePermit::new(
            global_permit,
            origin_permit,
            Arc::clone(&self.metrics),
        ))
    }

    async fn acquire_origin_permit(
        &self,
        origin: &str,
        pool_timeout: f64,
        started: Instant,
    ) -> PyResult<Option<OwnedSemaphorePermit>> {
        let Some(origin_gates) = &self.origin_gates else {
            return Ok(None);
        };

        let semaphore = origin_gates.semaphore(origin);
        self.acquire_semaphore(semaphore, remaining_duration(pool_timeout, started)?)
            .await
            .map(Some)
    }

    async fn acquire_semaphore(
        &self,
        semaphore: Arc<Semaphore>,
        timeout: Duration,
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

        let pending =
            PendingAcquire::try_start(Arc::clone(&self.metrics), self.max_pending_requests)?;
        let acquire_result = tokio::time::timeout(timeout, semaphore.acquire_owned()).await;
        drop(pending);

        match acquire_result {
            Ok(Ok(permit)) => Ok(permit),
            Ok(Err(err)) => Err(FogHttpError::new_err(err.to_string())),
            Err(_elapsed) => {
                self.metrics.pool_acquire_timeout();
                Err(FogHttpPoolTimeoutError::new_err(POOL_ACQUIRE_TIMEOUT))
            }
        }
    }
}

fn remaining_duration(pool_timeout: f64, started: Instant) -> PyResult<Duration> {
    numeric::remaining_duration("Timeouts.pool", pool_timeout, started)
        .map_err(PyValueError::new_err)
}
