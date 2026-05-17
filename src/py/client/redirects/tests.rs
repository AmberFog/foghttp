use super::{
    redirect_decision, redirect_headers, RedirectAction, RedirectDecision, RedirectHeaderPolicy,
};
use crate::core::headers::HeaderPairs;
use crate::core::method::{GET, POST};
use crate::messages::HTTPS_TO_HTTP_REDIRECT_BLOCKED;
use hyper::StatusCode;

fn header_names(headers: &HeaderPairs) -> Vec<String> {
    headers
        .iter()
        .map(|(name, _value)| name.to_owned())
        .collect()
}

fn follow_action(decision: Option<RedirectDecision>) -> RedirectAction {
    match decision.expect("redirect decision") {
        RedirectDecision::Follow(action) => action,
        RedirectDecision::Block(reason) => panic!("unexpected blocked redirect: {reason}"),
    }
}

#[test]
fn same_origin_redirect_keeps_sensitive_headers() {
    let action = follow_action(redirect_decision(
        GET,
        "https://example.com/users",
        StatusCode::FOUND.as_u16(),
        &[("location".to_owned(), "/accounts".to_owned())],
    ));

    let headers = redirect_headers(
        vec![
            ("Authorization".to_owned(), "Bearer token".to_owned()),
            ("Cookie".to_owned(), "session=1".to_owned()),
            ("Host".to_owned(), "example.com".to_owned()),
            ("Origin".to_owned(), "https://example.com".to_owned()),
            ("Referer".to_owned(), "https://example.com/users".to_owned()),
        ],
        RedirectHeaderPolicy {
            preserve_body: action.preserve_body,
            remove_sensitive_headers: action.remove_sensitive_headers,
        },
    );

    assert_eq!(
        header_names(&headers),
        vec!["Authorization", "Cookie", "Host", "Origin", "Referer"]
    );
}

#[test]
fn cross_origin_redirect_strips_sensitive_headers() {
    let action = follow_action(redirect_decision(
        GET,
        "https://example.com/users",
        StatusCode::FOUND.as_u16(),
        &[(
            "location".to_owned(),
            "https://api.example.org/final".to_owned(),
        )],
    ));

    let headers = redirect_headers(
        vec![
            ("Authorization".to_owned(), "Bearer token".to_owned()),
            ("Proxy-Authorization".to_owned(), "Basic token".to_owned()),
            ("Cookie".to_owned(), "session=1".to_owned()),
            ("Host".to_owned(), "example.com".to_owned()),
            ("Origin".to_owned(), "https://example.com".to_owned()),
            ("Referer".to_owned(), "https://example.com/users".to_owned()),
            ("Accept".to_owned(), "application/json".to_owned()),
        ],
        RedirectHeaderPolicy {
            preserve_body: action.preserve_body,
            remove_sensitive_headers: action.remove_sensitive_headers,
        },
    );

    assert_eq!(header_names(&headers), vec!["Accept"]);
}

#[test]
fn method_rewrite_strips_body_headers() {
    let action = follow_action(redirect_decision(
        POST,
        "https://example.com/users",
        StatusCode::SEE_OTHER.as_u16(),
        &[("location".to_owned(), "/final".to_owned())],
    ));

    let headers = redirect_headers(
        vec![
            ("Content-Type".to_owned(), "application/json".to_owned()),
            ("Content-Length".to_owned(), "12".to_owned()),
            ("Content-Encoding".to_owned(), "gzip".to_owned()),
            ("Transfer-Encoding".to_owned(), "chunked".to_owned()),
            ("Authorization".to_owned(), "Bearer token".to_owned()),
        ],
        RedirectHeaderPolicy {
            preserve_body: action.preserve_body,
            remove_sensitive_headers: action.remove_sensitive_headers,
        },
    );

    assert_eq!(action.method, GET);
    assert_eq!(header_names(&headers), vec!["Authorization"]);
}

#[test]
fn method_preserving_redirect_keeps_body_headers() {
    let action = follow_action(redirect_decision(
        POST,
        "https://example.com/users",
        StatusCode::TEMPORARY_REDIRECT.as_u16(),
        &[("location".to_owned(), "/final".to_owned())],
    ));

    let headers = redirect_headers(
        vec![
            ("Content-Type".to_owned(), "application/json".to_owned()),
            ("Content-Length".to_owned(), "12".to_owned()),
        ],
        RedirectHeaderPolicy {
            preserve_body: action.preserve_body,
            remove_sensitive_headers: action.remove_sensitive_headers,
        },
    );

    assert_eq!(action.method, POST);
    assert_eq!(
        header_names(&headers),
        vec!["Content-Type", "Content-Length"]
    );
}

#[test]
fn cross_origin_method_preserving_redirect_strips_body_headers() {
    let action = follow_action(redirect_decision(
        POST,
        "https://example.com/users",
        StatusCode::TEMPORARY_REDIRECT.as_u16(),
        &[(
            "location".to_owned(),
            "https://api.example.org/final".to_owned(),
        )],
    ));

    let headers = redirect_headers(
        vec![
            ("Content-Type".to_owned(), "application/json".to_owned()),
            ("Content-Length".to_owned(), "12".to_owned()),
            ("Transfer-Encoding".to_owned(), "chunked".to_owned()),
            ("Authorization".to_owned(), "Bearer token".to_owned()),
            ("Accept".to_owned(), "application/json".to_owned()),
        ],
        RedirectHeaderPolicy {
            preserve_body: action.preserve_body,
            remove_sensitive_headers: action.remove_sensitive_headers,
        },
    );

    assert_eq!(action.method, POST);
    assert!(!action.preserve_body);
    assert_eq!(header_names(&headers), vec!["Accept"]);
}

#[test]
fn https_to_http_redirect_is_blocked() {
    let decision = redirect_decision(
        POST,
        "https://example.com/users",
        StatusCode::TEMPORARY_REDIRECT.as_u16(),
        &[("location".to_owned(), "http://example.com/final".to_owned())],
    )
    .expect("redirect decision");

    match decision {
        RedirectDecision::Block(reason) => assert_eq!(reason, HTTPS_TO_HTTP_REDIRECT_BLOCKED),
        RedirectDecision::Follow(_) => panic!("expected blocked redirect"),
    }
}
