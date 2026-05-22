use super::{RequestState, TransportRequest};
use crate::core::headers::HeaderPairs;
use crate::core::method::{GET, POST};
use crate::core::metrics::Metrics;
use crate::core::response::BufferedBodyBudget;
use crate::messages::NON_REPLAYABLE_REQUEST_BODY_REDIRECT;
use crate::py::client::redirects::RedirectAction;
use pyo3::Python;
use std::sync::Arc;
use std::sync::Once;

const INITIAL_URL: &str = "http://example.com/start";
const REDIRECT_URL: &str = "http://example.com/next";
const TOTAL_TIMEOUT: f64 = 30.0;

fn initialize_python() {
    static PYTHON: Once = Once::new();
    PYTHON.call_once(Python::initialize);
}

#[test]
fn method_preserving_redirect_rejects_non_replayable_body() {
    initialize_python();
    let mut state = request_state(Some(vec![1, 2, 3]), false);

    let error = state
        .apply_redirect(redirect_action(POST, true))
        .expect_err("non-replayable body should reject method-preserving redirect");

    assert!(error
        .to_string()
        .contains(NON_REPLAYABLE_REQUEST_BODY_REDIRECT));
}

#[test]
fn method_rewriting_redirect_drops_non_replayable_body() {
    let mut state = request_state(Some(vec![1, 2, 3]), false);

    state
        .apply_redirect(redirect_action(GET, false))
        .expect("method-rewriting redirect should drop non-replayable body");

    assert!(state.body.is_none());
    assert!(state.body_replayability.can_replay());
}

#[test]
fn empty_body_is_replayable_even_when_boundary_flag_is_false() {
    let state = request_state(None, false);

    assert!(state.body_replayability.can_replay());
}

#[test]
fn empty_buffered_body_is_replayable_even_when_boundary_flag_is_false() {
    let state = request_state(Some(Vec::new()), false);

    assert!(state.body_replayability.can_replay());
}

fn request_state(body: Option<Vec<u8>>, body_replayable: bool) -> RequestState {
    RequestState::try_from(TransportRequest {
        method: POST.to_owned(),
        url: INITIAL_URL.to_owned(),
        headers: HeaderPairs::new(),
        body,
        body_replayable,
        total_timeout: TOTAL_TIMEOUT,
        max_response_body_size: None,
        buffered_body_budget: BufferedBodyBudget::new(None, Arc::new(Metrics::default())),
        follow_redirects: true,
        max_redirects: 20,
    })
    .expect("valid request state")
}

fn redirect_action(method: &str, preserve_body: bool) -> RedirectAction {
    RedirectAction {
        method: method.to_owned(),
        preserve_body,
        remove_sensitive_headers: false,
        url: REDIRECT_URL.to_owned(),
    }
}
