use crate::core::metrics::Metrics;
use crate::errors::FogHttpPoolTimeoutError;
use crate::messages::POOL_ACQUIRE_QUEUE_FULL;
use pyo3::prelude::*;
use std::sync::Arc;
use std::time::Instant;

pub struct PendingAcquire {
    metrics: Arc<Metrics>,
    started: Instant,
}

impl PendingAcquire {
    pub fn try_start(metrics: Arc<Metrics>, max_pending_requests: usize) -> PyResult<Self> {
        if metrics.pending_request_started(max_pending_requests) {
            Ok(Self {
                metrics,
                started: Instant::now(),
            })
        } else {
            metrics.pool_acquire_timeout();
            Err(FogHttpPoolTimeoutError::new_err(POOL_ACQUIRE_QUEUE_FULL))
        }
    }
}

impl Drop for PendingAcquire {
    fn drop(&mut self) {
        self.metrics.pending_request_finished();
        self.metrics
            .pool_acquire_wait_finished(self.started.elapsed());
    }
}
