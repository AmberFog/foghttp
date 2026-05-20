use crate::core::metrics::{Metrics, OriginMetrics};
use std::sync::Arc;

pub struct AcquireTelemetry {
    metrics: Arc<Metrics>,
    origin_metrics: Arc<OriginMetrics>,
    waited: bool,
}

impl AcquireTelemetry {
    pub fn start(metrics: Arc<Metrics>, origin_metrics: Arc<OriginMetrics>) -> Self {
        metrics.pool_acquire_started();
        origin_metrics.pool_acquire_started();
        Self {
            metrics,
            origin_metrics,
            waited: false,
        }
    }

    pub fn mark_waited(&mut self) {
        if self.waited {
            return;
        }

        self.waited = true;
        self.metrics.pool_acquire_waited();
        self.origin_metrics.pool_acquire_waited();
    }

    pub fn finish_success(&self) {
        if !self.waited {
            self.metrics.pool_acquire_finished_immediately();
            self.origin_metrics.pool_acquire_finished_immediately();
        }
    }
}
