use super::error::PolicyError;
use super::{
    PolicyMutation, PolicyPipeline, PolicyRequest, RequestBodyMutation, RequestBodyPolicy,
    ResponseHead, ResponsePolicyAction, TransportRoute,
};
use crate::core::headers::HeaderPairs;
use crate::core::method::{GET, POST};
use crate::core::url::HttpUrl;
use hyper::StatusCode;

const INITIAL_URL: &str = "http://example.com/start";

#[test]
fn default_pipeline_uses_direct_route_and_skips_response_policy() {
    let url = HttpUrl::parse(INITIAL_URL).expect("valid URL");
    let pipeline = pipeline("direct", false, false, 0, &url);
    let request = request(GET, &url, RequestBodyPolicy::Empty);

    assert_eq!(
        pipeline.before_send(request).expect("direct route"),
        TransportRoute::Direct
    );
    let headers = redirect_headers("/next");
    assert!(pipeline
        .on_response_headers(
            request,
            ResponseHead::new(StatusCode::FOUND.as_u16(), &headers),
        )
        .is_none());
}

#[test]
fn explicit_proxy_routes_redirect_hops_through_proxy() {
    let initial_url = HttpUrl::parse(INITIAL_URL).expect("valid URL");
    let next_url = HttpUrl::parse("https://example.com/secure").expect("valid URL");
    let pipeline = pipeline("explicit_proxy", false, true, 20, &initial_url);

    assert_eq!(
        pipeline
            .before_send(request(GET, &next_url, RequestBodyPolicy::Empty))
            .expect("proxy route"),
        TransportRoute::Proxy
    );
}

#[test]
fn proxy_policy_modes_own_route_selection() {
    let url = HttpUrl::parse(INITIAL_URL).expect("valid URL");
    let request = request(GET, &url, RequestBodyPolicy::Empty);

    let direct = pipeline("direct", true, false, 0, &url);
    assert_eq!(
        direct.before_send(request).expect("direct policy route"),
        TransportRoute::Direct,
    );

    let environment_direct = pipeline("environment_proxy", false, false, 0, &url);
    assert_eq!(
        environment_direct
            .before_send(request)
            .expect("same-origin environment route"),
        TransportRoute::Direct,
    );

    let environment_proxy = pipeline("environment_proxy", true, false, 0, &url);
    assert_eq!(
        environment_proxy
            .before_send(request)
            .expect("same-origin environment route"),
        TransportRoute::Proxy,
    );
}

#[test]
fn unknown_proxy_policy_is_rejected_at_pipeline_creation() {
    let url = HttpUrl::parse(INITIAL_URL).expect("valid URL");

    let error = PolicyPipeline::new("unknown", false, &url, false, 0, None)
        .expect_err("unknown proxy policy should fail closed");

    assert_eq!(error, PolicyError::InvalidProxyPolicy("unknown".to_owned()));
}

#[test]
fn environment_proxy_rejects_cross_origin_redirect_after_body_completion() {
    let initial_url = HttpUrl::parse(INITIAL_URL).expect("valid URL");
    let pipeline = pipeline("environment_proxy", true, true, 20, &initial_url);
    let request = request(GET, &initial_url, RequestBodyPolicy::Empty);
    let action = response_action(
        &pipeline,
        request,
        StatusCode::FOUND,
        "http://api.example.com/next",
    );

    let error = expect_policy_error(pipeline.after_response_body(request, action, 0));

    assert_eq!(error, PolicyError::ProxyRedirectPolicyRecomputeUnsupported);
}

#[test]
fn method_preserving_redirect_rejects_non_replayable_body() {
    let url = HttpUrl::parse(INITIAL_URL).expect("valid URL");
    let pipeline = pipeline("direct", false, true, 20, &url);
    let request = request(POST, &url, RequestBodyPolicy::NonReplayable);
    let action = response_action(&pipeline, request, StatusCode::TEMPORARY_REDIRECT, "/next");

    let error = expect_policy_error(pipeline.after_response_body(request, action, 0));

    assert_eq!(error, PolicyError::NonReplayableRequestBodyRedirect);
}

#[test]
fn redirect_limit_is_enforced_after_redirect_body_completion() {
    let url = HttpUrl::parse(INITIAL_URL).expect("valid URL");
    let pipeline = pipeline("direct", false, true, 1, &url);
    let request = request(GET, &url, RequestBodyPolicy::Empty);
    let action = response_action(&pipeline, request, StatusCode::FOUND, "/next");

    let error = expect_policy_error(pipeline.after_response_body(request, action, 1));

    assert_eq!(
        error,
        PolicyError::RedirectLimitExceeded {
            max_redirects: 1,
            origin: "http://example.com".to_owned(),
        }
    );
}

#[test]
fn method_rewrite_returns_typed_body_drop_mutation() {
    let url = HttpUrl::parse(INITIAL_URL).expect("valid URL");
    let pipeline = pipeline("direct", false, true, 20, &url);
    let request = request(POST, &url, RequestBodyPolicy::NonReplayable);
    let action = response_action(&pipeline, request, StatusCode::SEE_OTHER, "/next");

    let mutation = pipeline
        .after_response_body(request, action, 0)
        .expect("method rewrite can drop a non-replayable body");

    let PolicyMutation::Redirect { body, method, .. } = mutation;
    assert_eq!(method, GET);
    assert_eq!(body, RequestBodyMutation::Drop);
}

fn pipeline(
    proxy_policy: &str,
    initial_use_proxy_transport: bool,
    follow_redirects: bool,
    max_redirects: usize,
    initial_url: &HttpUrl,
) -> PolicyPipeline {
    PolicyPipeline::new(
        proxy_policy,
        initial_use_proxy_transport,
        initial_url,
        follow_redirects,
        max_redirects,
        None,
    )
    .expect("valid policy pipeline")
}

fn request<'a>(method: &'a str, url: &'a HttpUrl, body: RequestBodyPolicy) -> PolicyRequest<'a> {
    PolicyRequest::new(method, url, body)
}

fn response_action(
    pipeline: &PolicyPipeline,
    request: PolicyRequest<'_>,
    status: StatusCode,
    location: &str,
) -> ResponsePolicyAction {
    let headers = redirect_headers(location);
    pipeline
        .on_response_headers(request, ResponseHead::new(status.as_u16(), &headers))
        .expect("redirect action")
}

fn redirect_headers(location: &str) -> HeaderPairs {
    vec![("location".to_owned(), location.to_owned())]
}

fn expect_policy_error(result: Result<PolicyMutation, PolicyError>) -> PolicyError {
    match result {
        Ok(_) => panic!("policy evaluation should fail closed"),
        Err(error) => error,
    }
}
