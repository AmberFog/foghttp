#[cfg(test)]
mod tests;

use crate::core::metrics::{Metrics, OriginMetrics, ResponseBodyLifecycleOutcome};
use hyper::header::CONNECTION;
use hyper::{HeaderMap, Version};
use std::sync::Arc;

pub struct ResponseBodyLifecycle {
    metrics: Arc<Metrics>,
    origin_metrics: Arc<OriginMetrics>,
    outcome: Option<ResponseBodyLifecycleOutcome>,
}

impl ResponseBodyLifecycle {
    pub fn new(metrics: Arc<Metrics>, origin_metrics: Arc<OriginMetrics>) -> Self {
        Self {
            metrics,
            origin_metrics,
            outcome: None,
        }
    }

    pub fn finish(&mut self, outcome: ResponseBodyLifecycleOutcome) {
        if self.outcome.is_some() {
            return;
        }

        self.metrics.response_body_finished(outcome);
        self.origin_metrics.response_body_finished(outcome);
        self.outcome = Some(outcome);
    }
}

impl Drop for ResponseBodyLifecycle {
    fn drop(&mut self) {
        self.finish(ResponseBodyLifecycleOutcome::Aborted);
    }
}

pub fn successful_response_body_outcome(
    version: Version,
    headers: &HeaderMap,
) -> ResponseBodyLifecycleOutcome {
    if connection_close_requested(headers) || !http_version_reuses_by_default(version) {
        ResponseBodyLifecycleOutcome::Closed
    } else {
        ResponseBodyLifecycleOutcome::ReuseEligible
    }
}

fn http_version_reuses_by_default(version: Version) -> bool {
    !matches!(version, Version::HTTP_09 | Version::HTTP_10)
}

fn connection_close_requested(headers: &HeaderMap) -> bool {
    headers
        .get_all(CONNECTION)
        .iter()
        .filter_map(|value| value.to_str().ok())
        .flat_map(|value| value.split(','))
        .any(|token| token.trim().eq_ignore_ascii_case("close"))
}
