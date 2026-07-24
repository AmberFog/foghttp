use super::request::{PendingResponsePolicyAction, RequestState, TransportRequest};
use crate::core::headers::HeaderPairs;
use crate::core::method::{GET, POST};
use crate::core::metrics::Metrics;
use crate::core::policy::TransportRoute;
use crate::core::response::BufferedBodyBudget;
use crate::messages::{
    NON_REPLAYABLE_REQUEST_BODY_REDIRECT, PROXY_REDIRECT_POLICY_RECOMPUTE_UNSUPPORTED,
};
use hyper::StatusCode;
use pyo3::Python;
use std::sync::{Arc, Once};
use tokio::runtime::Builder;

const INITIAL_URL: &str = "http://example.com/start";
const READ_TIMEOUT: f64 = 10.0;
const TOTAL_TIMEOUT: f64 = 30.0;
const WRITE_TIMEOUT: f64 = 2.0;

fn initialize_python() {
    static PYTHON: Once = Once::new();
    PYTHON.call_once(Python::initialize);
}

#[test]
fn method_preserving_redirect_rejects_non_replayable_body() {
    initialize_python();
    let mut state = request_state(Some(vec![1, 2, 3]), false);
    let action = response_action(&mut state, StatusCode::TEMPORARY_REDIRECT, "/next");

    let error = state
        .after_response_body(action, 0)
        .expect_err("non-replayable body should reject method-preserving redirect");

    assert!(error
        .to_string()
        .contains(NON_REPLAYABLE_REQUEST_BODY_REDIRECT));
}

#[test]
fn method_rewriting_redirect_drops_non_replayable_body() {
    let mut state = request_state(Some(vec![1, 2, 3]), false);
    let action = response_action(&mut state, StatusCode::SEE_OTHER, "/next");

    state
        .after_response_body(action, 0)
        .expect("method-rewriting redirect should drop non-replayable body");

    assert!(!state.has_request_body());
    assert!(state.body_policy.can_replay());
}

#[test]
fn empty_body_is_replayable_even_when_boundary_flag_is_false() {
    let state = request_state(None, false);

    assert!(state.body_policy.can_replay());
}

#[test]
fn empty_buffered_body_is_replayable_even_when_boundary_flag_is_false() {
    let state = request_state(Some(Vec::new()), false);

    assert!(state.body_policy.can_replay());
}

#[test]
fn write_timeout_context_exists_only_for_non_empty_request_body() {
    let empty_state = request_state(Some(Vec::new()), true);
    let body_state = request_state(Some(vec![1, 2, 3]), true);

    assert!(empty_state.write_timeout_context(INITIAL_URL, 0).is_none());
    assert!(body_state.write_timeout_context(INITIAL_URL, 0).is_some());
}

#[test]
fn request_info_excludes_transport_proxy_authorization() {
    let mut parts = transport_request(None, true);
    parts.method = GET.to_owned();
    parts.follow_redirects = false;
    parts.max_redirects = 0;
    parts.proxy_authorization = Some("Basic secret".to_owned());
    parts.proxy_policy = "explicit_proxy".to_owned();
    parts.use_proxy_transport = true;
    let mut state = RequestState::try_from(parts).expect("valid request state");

    assert!(state.request_info().headers.is_empty());
    assert_eq!(
        state
            .take_request_parts(TransportRoute::Proxy)
            .expect("valid request parts")
            .proxy_authorization,
        Some("Basic secret".to_owned()),
    );
}

#[test]
fn explicit_proxy_tunnels_https_redirect_via_connect() {
    let mut parts = transport_request(None, true);
    parts.method = GET.to_owned();
    parts.proxy_authorization = Some("Basic secret".to_owned());
    parts.proxy_policy = "explicit_proxy".to_owned();
    parts.use_proxy_transport = true;
    let mut state = RequestState::try_from(parts).expect("valid request state");
    let action = response_action(&mut state, StatusCode::FOUND, "https://example.com/secure");

    state
        .after_response_body(action, 0)
        .expect("explicit proxy should tunnel https redirects via CONNECT");

    assert_eq!(state.url.as_str(), "https://example.com/secure");
    assert_eq!(
        test_runtime()
            .block_on(state.transport_route(1))
            .expect("explicit proxy routes https targets through the proxy"),
        TransportRoute::Proxy
    );
    assert_eq!(
        state
            .take_request_parts(TransportRoute::Proxy)
            .expect("valid request parts")
            .proxy_authorization,
        None,
    );
}

fn test_runtime() -> tokio::runtime::Runtime {
    Builder::new_current_thread().build().unwrap()
}

#[test]
fn environment_proxy_blocks_cross_origin_redirect_until_per_hop_decisions_exist() {
    initialize_python();
    let mut parts = transport_request(None, true);
    parts.method = GET.to_owned();
    parts.proxy_policy = "environment_proxy".to_owned();
    parts.use_proxy_transport = true;
    let mut state = RequestState::try_from(parts).expect("valid request state");
    let action = response_action(&mut state, StatusCode::FOUND, "http://api.example.com/next");

    let error = state
        .after_response_body(action, 0)
        .expect_err("cross-origin env proxy redirect should fail closed");

    assert!(error
        .to_string()
        .contains(PROXY_REDIRECT_POLICY_RECOMPUTE_UNSUPPORTED));
}

fn request_state(body: Option<Vec<u8>>, body_replayable: bool) -> RequestState {
    RequestState::try_from(transport_request(body, body_replayable)).expect("valid request state")
}

fn transport_request(body: Option<Vec<u8>>, body_replayable: bool) -> TransportRequest {
    TransportRequest {
        method: POST.to_owned(),
        url: INITIAL_URL.to_owned(),
        headers: HeaderPairs::new(),
        auth_override_headers: None,
        auth_removed_headers: Vec::new(),
        body,
        body_stream: None,
        body_replayable,
        use_proxy_transport: false,
        proxy_policy: "direct".to_owned(),
        proxy_authorization: None,
        total_timeout: TOTAL_TIMEOUT,
        read_timeout: READ_TIMEOUT,
        write_timeout: WRITE_TIMEOUT,
        max_response_body_size: None,
        buffered_body_budget: BufferedBodyBudget::new(None, Arc::new(Metrics::default())),
        follow_redirects: true,
        max_redirects: 20,
        retry_policy: None,
        ssrf_policy: None,
        auth: None,
        policy_hooks: None,
        extensions: None,
    }
}

fn response_action(
    state: &mut RequestState,
    status: StatusCode,
    location: &str,
) -> PendingResponsePolicyAction {
    let headers = vec![("location".to_owned(), location.to_owned())];
    state
        .on_response_headers(status.as_u16(), &headers, 0)
        .expect("valid response policy evaluation")
        .expect("redirect action")
}
