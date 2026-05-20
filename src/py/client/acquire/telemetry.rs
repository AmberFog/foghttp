use crate::core::metrics::Metrics;
use std::sync::Arc;

pub struct AcquireTelemetry {
    metrics: Arc<Metrics>,
    waited: bool,
}

impl AcquireTelemetry {
    pub fn start(metrics: Arc<Metrics>) -> Self {
        metrics.pool_acquire_started();
        Self {
            metrics,
            waited: false,
        }
    }

    pub fn mark_waited(&mut self) {
        if self.waited {
            return;
        }

        self.waited = true;
        self.metrics.pool_acquire_waited();
    }

    pub fn finish_success(&self) {
        if !self.waited {
            self.metrics.pool_acquire_finished_immediately();
        }
    }
}
