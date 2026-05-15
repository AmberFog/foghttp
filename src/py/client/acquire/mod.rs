#[cfg(test)]
mod tests;

use crate::core::metrics::Metrics;
use crate::errors::{FogHttpError, FogHttpTimeoutError};
use crate::messages::{POOL_ACQUIRE_QUEUE_FULL, POOL_ACQUIRE_TIMEOUT};
use pyo3::prelude::*;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::{OwnedSemaphorePermit, Semaphore, TryAcquireError};

#[derive(Clone)]
pub struct AcquireGate {
    max_pending_requests: usize,
    metrics: Arc<Metrics>,
    semaphore: Arc<Semaphore>,
}

impl AcquireGate {
    pub fn new(
        max_active_requests: usize,
        max_pending_requests: usize,
        metrics: Arc<Metrics>,
    ) -> Self {
        Self {
            max_pending_requests,
            metrics,
            semaphore: Arc::new(Semaphore::new(max_active_requests)),
        }
    }

    pub async fn acquire(&self, pool_timeout: f64) -> PyResult<AcquirePermit> {
        match Arc::clone(&self.semaphore).try_acquire_owned() {
            Ok(permit) => {
                return Ok(AcquirePermit::new(permit, Arc::clone(&self.metrics)));
            }
            Err(TryAcquireError::NoPermits) => {}
            Err(TryAcquireError::Closed) => {
                return Err(FogHttpError::new_err("acquire gate is closed"))
            }
        }

        let pending =
            PendingAcquire::try_start(Arc::clone(&self.metrics), self.max_pending_requests)?;
        let duration = Duration::from_secs_f64(pool_timeout.max(0.0));
        let acquire_result =
            tokio::time::timeout(duration, Arc::clone(&self.semaphore).acquire_owned()).await;
        drop(pending);

        match acquire_result {
            Ok(Ok(permit)) => Ok(AcquirePermit::new(permit, Arc::clone(&self.metrics))),
            Ok(Err(err)) => Err(FogHttpError::new_err(err.to_string())),
            Err(_elapsed) => {
                self.metrics.pool_acquire_timeout();
                Err(FogHttpTimeoutError::new_err(POOL_ACQUIRE_TIMEOUT))
            }
        }
    }
}

pub struct AcquirePermit {
    metrics: Arc<Metrics>,
    _permit: OwnedSemaphorePermit,
}

impl AcquirePermit {
    fn new(permit: OwnedSemaphorePermit, metrics: Arc<Metrics>) -> Self {
        metrics.active_request_started();
        Self {
            metrics,
            _permit: permit,
        }
    }
}

impl Drop for AcquirePermit {
    fn drop(&mut self) {
        self.metrics.active_request_finished();
    }
}

struct PendingAcquire {
    metrics: Arc<Metrics>,
}

impl PendingAcquire {
    fn try_start(metrics: Arc<Metrics>, max_pending_requests: usize) -> PyResult<Self> {
        if metrics.pending_request_started(max_pending_requests) {
            Ok(Self { metrics })
        } else {
            metrics.pool_acquire_timeout();
            Err(FogHttpTimeoutError::new_err(POOL_ACQUIRE_QUEUE_FULL))
        }
    }
}

impl Drop for PendingAcquire {
    fn drop(&mut self) {
        self.metrics.pending_request_finished();
    }
}
