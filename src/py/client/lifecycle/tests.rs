use super::{successful_response_body_outcome, ResponseBodyLifecycle};
use crate::core::metrics::{Metrics, ResponseBodyLifecycleOutcome};
use hyper::header::{HeaderValue, CONNECTION};
use hyper::{HeaderMap, Version};
use std::sync::Arc;

const ORIGIN: &str = "https://api.example.com";

#[test]
fn clean_http11_response_is_reuse_eligible_by_default() {
    let headers = HeaderMap::new();

    let outcome = successful_response_body_outcome(Version::HTTP_11, &headers);

    assert_eq!(outcome, ResponseBodyLifecycleOutcome::ReuseEligible);
}

#[test]
fn clean_response_with_connection_close_is_closed() {
    let mut headers = HeaderMap::new();
    headers.insert(CONNECTION, HeaderValue::from_static("keep-alive, close"));

    let outcome = successful_response_body_outcome(Version::HTTP_11, &headers);

    assert_eq!(outcome, ResponseBodyLifecycleOutcome::Closed);
}

#[test]
fn clean_http10_response_is_closed_by_default() {
    let headers = HeaderMap::new();

    let outcome = successful_response_body_outcome(Version::HTTP_10, &headers);

    assert_eq!(outcome, ResponseBodyLifecycleOutcome::Closed);
}

#[test]
fn lifecycle_finish_records_single_successful_outcome() {
    let metrics = Arc::new(Metrics::default());
    let origin_metrics = metrics.origin_metrics(ORIGIN);
    let mut lifecycle = ResponseBodyLifecycle::new(Arc::clone(&metrics), origin_metrics);

    lifecycle.finish(ResponseBodyLifecycleOutcome::ReuseEligible);
    lifecycle.finish(ResponseBodyLifecycleOutcome::Closed);
    drop(lifecycle);

    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.response_body_reuse_eligible, 1);
    assert_eq!(snapshot.response_body_closed, 0);
    assert_eq!(snapshot.response_body_aborted, 0);
}

#[test]
fn lifecycle_drop_records_abort_when_unfinished() {
    let metrics = Arc::new(Metrics::default());
    let origin_metrics = metrics.origin_metrics(ORIGIN);

    drop(ResponseBodyLifecycle::new(
        Arc::clone(&metrics),
        origin_metrics,
    ));

    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.response_body_reuse_eligible, 0);
    assert_eq!(snapshot.response_body_closed, 0);
    assert_eq!(snapshot.response_body_aborted, 1);
}
