use super::{RetryDecision, RetryPolicy, RetryStopReason, MAX_RETRY_DELAY};
use crate::core::headers::HeaderPairs;
use crate::core::policy::{PolicyRequest, RequestBodyPolicy, ResponseHead};
use crate::core::url::HttpUrl;
use std::sync::OnceLock;
use std::time::{Duration, SystemTime};

const SERVICE_UNAVAILABLE: u16 = 503;

#[test]
fn retries_matching_safe_response_with_exponential_backoff_and_jitter() {
    let policy = policy(2, vec![SERVICE_UNAVAILABLE], vec!["GET"]);
    let request = request("GET", RequestBodyPolicy::Empty);
    let headers = HeaderPairs::new();

    let decision = policy.on_response(
        request,
        ResponseHead::new(SERVICE_UNAVAILABLE, &headers),
        1,
        0.5,
        SystemTime::UNIX_EPOCH,
    );

    assert_eq!(
        decision,
        Some(RetryDecision::Retry {
            delay: Duration::from_millis(450),
        })
    );
}

#[test]
fn retry_after_is_a_minimum_delay() {
    let policy = policy(1, vec![SERVICE_UNAVAILABLE], vec!["GET"]);
    let request = request("GET", RequestBodyPolicy::Empty);
    let headers = vec![("Retry-After".to_owned(), "2".to_owned())];

    let decision = policy.on_response(
        request,
        ResponseHead::new(SERVICE_UNAVAILABLE, &headers),
        0,
        0.0,
        SystemTime::UNIX_EPOCH,
    );

    assert_eq!(
        decision,
        Some(RetryDecision::Retry {
            delay: Duration::from_secs(2),
        })
    );
}

#[test]
fn caps_untrusted_retry_after_delay() {
    let policy = policy(1, vec![SERVICE_UNAVAILABLE], vec!["GET"]);
    let request = request("GET", RequestBodyPolicy::Empty);
    let headers = vec![("Retry-After".to_owned(), u64::MAX.to_string())];

    let decision = policy.on_response(
        request,
        ResponseHead::new(SERVICE_UNAVAILABLE, &headers),
        0,
        0.0,
        SystemTime::UNIX_EPOCH,
    );

    assert_eq!(
        decision,
        Some(RetryDecision::Retry {
            delay: MAX_RETRY_DELAY,
        })
    );
}

#[test]
fn past_retry_after_date_adds_no_delay() {
    let policy = policy(1, vec![SERVICE_UNAVAILABLE], vec!["GET"]);
    let request = request("GET", RequestBodyPolicy::Empty);
    let headers = vec![(
        "Retry-After".to_owned(),
        "Thu, 01 Jan 1970 00:00:00 GMT".to_owned(),
    )];

    let decision = policy.on_response(
        request,
        ResponseHead::new(SERVICE_UNAVAILABLE, &headers),
        0,
        0.0,
        SystemTime::UNIX_EPOCH + Duration::from_secs(1),
    );

    assert_eq!(
        decision,
        Some(RetryDecision::Retry {
            delay: Duration::from_millis(200),
        })
    );
}

#[test]
fn future_retry_after_date_is_a_minimum_delay() {
    let policy = policy(1, vec![SERVICE_UNAVAILABLE], vec!["GET"]);
    let request = request("GET", RequestBodyPolicy::Empty);
    let headers = vec![(
        "Retry-After".to_owned(),
        "Thu, 01 Jan 1970 00:00:02 GMT".to_owned(),
    )];

    let decision = policy.on_response(
        request,
        ResponseHead::new(SERVICE_UNAVAILABLE, &headers),
        0,
        0.0,
        SystemTime::UNIX_EPOCH,
    );

    assert_eq!(
        decision,
        Some(RetryDecision::Retry {
            delay: Duration::from_secs(2),
        })
    );
}

#[test]
fn malformed_retry_after_uses_configured_delay() {
    let policy = policy(1, vec![SERVICE_UNAVAILABLE], vec!["GET"]);
    let request = request("GET", RequestBodyPolicy::Empty);
    let headers = vec![("Retry-After".to_owned(), "not-a-delay".to_owned())];

    let decision = policy.on_response(
        request,
        ResponseHead::new(SERVICE_UNAVAILABLE, &headers),
        0,
        0.0,
        SystemTime::UNIX_EPOCH,
    );

    assert_eq!(
        decision,
        Some(RetryDecision::Retry {
            delay: Duration::from_millis(200),
        })
    );
}

#[test]
fn ignores_unconfigured_status_and_network_errors() {
    let policy =
        RetryPolicy::new(1, 0.0, 0.0, vec![], vec!["GET".to_owned()], false).expect("valid policy");
    let request = request("GET", RequestBodyPolicy::Empty);
    let headers = HeaderPairs::new();

    assert_eq!(
        policy.on_response(
            request,
            ResponseHead::new(SERVICE_UNAVAILABLE, &headers),
            0,
            0.0,
            SystemTime::UNIX_EPOCH,
        ),
        None,
    );
    assert_eq!(policy.on_network_error(request, 0, 0.0), None);
}

#[test]
fn blocks_non_replayable_body_before_retrying() {
    let policy = policy(1, vec![SERVICE_UNAVAILABLE], vec!["QUERY"]);

    assert_eq!(
        policy.on_network_error(request("QUERY", RequestBodyPolicy::NonReplayable), 0, 0.0,),
        Some(RetryDecision::Stop {
            reason: RetryStopReason::NonReplayableBody,
        }),
    );
}

#[test]
fn stops_method_not_in_explicit_allowlist() {
    let policy = policy(1, vec![SERVICE_UNAVAILABLE], vec!["GET"]);

    assert_eq!(
        policy.on_network_error(request("POST", RequestBodyPolicy::Replayable), 0, 0.0),
        Some(RetryDecision::Stop {
            reason: RetryStopReason::MethodNotAllowed,
        }),
    );
}

#[test]
fn stops_after_configured_retries_are_exhausted() {
    let policy = policy(1, vec![SERVICE_UNAVAILABLE], vec!["GET"]);

    assert_eq!(
        policy.on_network_error(request("GET", RequestBodyPolicy::Empty), 1, 0.0),
        Some(RetryDecision::Stop {
            reason: RetryStopReason::RetriesExhausted,
        }),
    );
}

#[test]
fn rejects_invalid_status_and_method_at_native_boundary() {
    assert!(RetryPolicy::new(1, 0.0, 0.0, vec![99], vec!["GET".to_owned()], true).is_err());
    assert!(RetryPolicy::new(
        1,
        0.0,
        0.0,
        vec![SERVICE_UNAVAILABLE],
        vec!["not a method".to_owned()],
        true,
    )
    .is_err());
}

#[test]
fn normalizes_methods_at_native_boundary() {
    let policy = RetryPolicy::new(
        1,
        0.0,
        0.0,
        vec![SERVICE_UNAVAILABLE],
        vec!["get".to_owned()],
        true,
    )
    .expect("valid policy");

    assert!(matches!(
        policy.on_network_error(request("GET", RequestBodyPolicy::Empty), 0, 0.0),
        Some(RetryDecision::Retry { .. }),
    ));
}

fn policy(retries: usize, statuses: Vec<u16>, methods: Vec<&str>) -> RetryPolicy {
    RetryPolicy::new(
        retries,
        0.2,
        0.1,
        statuses,
        methods.into_iter().map(str::to_owned).collect(),
        true,
    )
    .expect("valid policy")
}

fn request(method: &str, body: RequestBodyPolicy) -> PolicyRequest<'_> {
    static URL: OnceLock<HttpUrl> = OnceLock::new();
    let url =
        URL.get_or_init(|| HttpUrl::parse("https://api.example.com/resource").expect("valid URL"));
    PolicyRequest::new(method, url, body)
}
