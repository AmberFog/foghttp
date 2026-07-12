use super::{redirect_decision, redirect_headers, RedirectAction, RedirectDecision};
use crate::core::headers::HeaderPairs;
use crate::core::method::{GET, POST, QUERY};
use crate::core::policy::error::PolicyError;
use crate::core::policy::request::{
    PolicyRequest, RequestBodyMutation, RequestBodyPolicy, ResponseHead,
};
use crate::core::url::HttpUrl;
use hyper::StatusCode;

fn header_names(headers: &HeaderPairs) -> Vec<String> {
    headers
        .iter()
        .map(|(name, _value)| name.to_owned())
        .collect()
}

fn decision(
    method: &str,
    url: &str,
    status_code: StatusCode,
    location: &str,
) -> Option<RedirectDecision> {
    let url = HttpUrl::parse(url).expect("valid URL");
    let headers = vec![("location".to_owned(), location.to_owned())];
    redirect_decision(
        PolicyRequest::new(method, &url, RequestBodyPolicy::Replayable),
        ResponseHead::new(status_code.as_u16(), &headers),
    )
}

fn follow_action(decision: Option<RedirectDecision>) -> RedirectAction {
    match decision.expect("redirect decision") {
        RedirectDecision::Follow(action) => action,
        RedirectDecision::Block(error) => panic!("unexpected blocked redirect: {error}"),
    }
}

#[test]
fn every_redirect_rebuilds_transport_and_connection_headers() {
    let action = follow_action(decision(
        GET,
        "https://example.com/users",
        StatusCode::FOUND,
        "/accounts",
    ));

    let headers = headers_after_redirect(
        &action,
        vec![
            ("Connection".to_owned(), "keep-alive, x-hop".to_owned()),
            ("Content-Length".to_owned(), "12".to_owned()),
            ("Host".to_owned(), "example.com".to_owned()),
            ("Keep-Alive".to_owned(), "timeout=5".to_owned()),
            ("Proxy-Authorization".to_owned(), "Basic token".to_owned()),
            ("Proxy-Connection".to_owned(), "keep-alive".to_owned()),
            ("TE".to_owned(), "trailers".to_owned()),
            ("Trailer".to_owned(), "x-checksum".to_owned()),
            ("Transfer-Encoding".to_owned(), "chunked".to_owned()),
            ("Upgrade".to_owned(), "websocket".to_owned()),
            ("X-Hop".to_owned(), "connection-specific".to_owned()),
            ("Accept".to_owned(), "application/json".to_owned()),
        ],
    );

    assert_eq!(header_names(&headers), vec!["Accept"]);
}

#[test]
fn every_redirect_strips_conditional_headers() {
    let action = follow_action(decision(
        GET,
        "https://example.com/users",
        StatusCode::FOUND,
        "/accounts",
    ));

    let headers = headers_after_redirect(
        &action,
        vec![
            ("If-Match".to_owned(), "\"etag\"".to_owned()),
            ("If-Modified-Since".to_owned(), "yesterday".to_owned()),
            ("If-None-Match".to_owned(), "\"etag\"".to_owned()),
            ("If-Range".to_owned(), "\"etag\"".to_owned()),
            ("If-Unmodified-Since".to_owned(), "yesterday".to_owned()),
            ("Accept".to_owned(), "application/json".to_owned()),
        ],
    );

    assert_eq!(header_names(&headers), vec!["Accept"]);
}

#[test]
fn same_origin_redirect_keeps_origin_scoped_headers() {
    let action = follow_action(decision(
        GET,
        "https://example.com/users",
        StatusCode::FOUND,
        "/accounts",
    ));

    let headers = headers_after_redirect(
        &action,
        vec![
            ("Authorization".to_owned(), "Bearer token".to_owned()),
            ("Cookie".to_owned(), "session=1".to_owned()),
            ("Origin".to_owned(), "https://example.com".to_owned()),
            ("Referer".to_owned(), "https://example.com/users".to_owned()),
            ("Accept".to_owned(), "application/json".to_owned()),
        ],
    );

    assert_eq!(
        header_names(&headers),
        vec!["Authorization", "Cookie", "Origin", "Referer", "Accept"]
    );
}

#[test]
fn cross_origin_redirect_strips_sensitive_headers() {
    let action = follow_action(decision(
        GET,
        "https://example.com/users",
        StatusCode::FOUND,
        "https://api.example.org/final",
    ));

    let headers = headers_after_redirect(
        &action,
        vec![
            ("Authorization".to_owned(), "Bearer token".to_owned()),
            ("Cookie".to_owned(), "session=1".to_owned()),
            ("Origin".to_owned(), "https://example.com".to_owned()),
            ("Referer".to_owned(), "https://example.com/users".to_owned()),
            ("Accept".to_owned(), "application/json".to_owned()),
        ],
    );

    assert_eq!(action.body, RequestBodyMutation::Drop);
    assert_eq!(header_names(&headers), vec!["Accept"]);
}

#[test]
fn method_rewrite_strips_body_headers() {
    let action = follow_action(decision(
        POST,
        "https://example.com/users",
        StatusCode::SEE_OTHER,
        "/final",
    ));

    let headers = headers_after_redirect(
        &action,
        vec![
            ("Content-Checksum".to_owned(), "custom-checksum".to_owned()),
            ("Content-Digest".to_owned(), "sha-256=:YWJj:".to_owned()),
            (
                "Content-Disposition".to_owned(),
                "attachment; filename=payload.txt".to_owned(),
            ),
            ("Content-Encoding".to_owned(), "gzip".to_owned()),
            ("Content-Language".to_owned(), "en".to_owned()),
            ("Content-Location".to_owned(), "/source".to_owned()),
            ("Content-Range".to_owned(), "bytes 0-2/3".to_owned()),
            ("Content-Type".to_owned(), "application/json".to_owned()),
            ("Content-Length".to_owned(), "12".to_owned()),
            ("Digest".to_owned(), "sha-256=YWJj".to_owned()),
            ("Last-Modified".to_owned(), "yesterday".to_owned()),
            ("Repr-Digest".to_owned(), "sha-256=:YWJj:".to_owned()),
            ("Transfer-Encoding".to_owned(), "chunked".to_owned()),
            ("Authorization".to_owned(), "Bearer token".to_owned()),
        ],
    );

    assert_eq!(action.method, GET);
    assert_eq!(action.body, RequestBodyMutation::Drop);
    assert_eq!(header_names(&headers), vec!["Authorization"]);
}

#[test]
fn method_preserving_redirect_keeps_body_headers() {
    let action = follow_action(decision(
        POST,
        "https://example.com/users",
        StatusCode::TEMPORARY_REDIRECT,
        "/final",
    ));

    let headers = headers_after_redirect(
        &action,
        vec![
            ("Content-Checksum".to_owned(), "custom-checksum".to_owned()),
            ("Content-Digest".to_owned(), "sha-256=:YWJj:".to_owned()),
            (
                "Content-Disposition".to_owned(),
                "attachment; filename=payload.txt".to_owned(),
            ),
            ("Content-Encoding".to_owned(), "identity".to_owned()),
            ("Content-Language".to_owned(), "en".to_owned()),
            ("Content-Location".to_owned(), "/source".to_owned()),
            ("Content-Range".to_owned(), "bytes 0-2/3".to_owned()),
            ("Content-Type".to_owned(), "application/json".to_owned()),
            ("Content-Length".to_owned(), "12".to_owned()),
            ("Digest".to_owned(), "sha-256=YWJj".to_owned()),
            ("Last-Modified".to_owned(), "yesterday".to_owned()),
            ("Repr-Digest".to_owned(), "sha-256=:YWJj:".to_owned()),
            ("Transfer-Encoding".to_owned(), "chunked".to_owned()),
        ],
    );

    assert_eq!(action.method, POST);
    assert_eq!(action.body, RequestBodyMutation::Preserve);
    assert_eq!(
        header_names(&headers),
        vec![
            "Content-Checksum",
            "Content-Digest",
            "Content-Disposition",
            "Content-Encoding",
            "Content-Language",
            "Content-Location",
            "Content-Range",
            "Content-Type",
            "Digest",
            "Last-Modified",
            "Repr-Digest",
        ]
    );
}

#[test]
fn query_redirects_preserve_method_except_for_see_other() {
    for status_code in [
        StatusCode::MOVED_PERMANENTLY,
        StatusCode::FOUND,
        StatusCode::TEMPORARY_REDIRECT,
        StatusCode::PERMANENT_REDIRECT,
    ] {
        let action = follow_action(decision(
            QUERY,
            "https://example.com/search",
            status_code,
            "/results",
        ));

        assert_eq!(action.method, QUERY);
        assert_eq!(action.body, RequestBodyMutation::Preserve);
    }

    let action = follow_action(decision(
        QUERY,
        "https://example.com/search",
        StatusCode::SEE_OTHER,
        "/results",
    ));

    assert_eq!(action.method, GET);
    assert_eq!(action.body, RequestBodyMutation::Drop);
}

#[test]
fn cross_origin_method_preserving_redirect_strips_body_headers() {
    let action = follow_action(decision(
        POST,
        "https://example.com/users",
        StatusCode::TEMPORARY_REDIRECT,
        "https://api.example.org/final",
    ));

    let headers = headers_after_redirect(
        &action,
        vec![
            ("Content-Type".to_owned(), "application/json".to_owned()),
            ("Content-Length".to_owned(), "12".to_owned()),
            ("Transfer-Encoding".to_owned(), "chunked".to_owned()),
            ("Authorization".to_owned(), "Bearer token".to_owned()),
            ("Accept".to_owned(), "application/json".to_owned()),
        ],
    );

    assert_eq!(action.method, POST);
    assert_eq!(action.body, RequestBodyMutation::Drop);
    assert_eq!(header_names(&headers), vec!["Accept"]);
}

fn headers_after_redirect(action: &RedirectAction, headers: HeaderPairs) -> HeaderPairs {
    redirect_headers(headers, action.body, action.header_policy)
}

#[test]
fn https_to_http_redirect_is_blocked() {
    let decision = decision(
        POST,
        "https://example.com/users",
        StatusCode::TEMPORARY_REDIRECT,
        "http://example.com/final",
    )
    .expect("redirect decision");

    match decision {
        RedirectDecision::Block(error) => {
            assert_eq!(error, PolicyError::HttpsToHttpRedirectBlocked);
        }
        RedirectDecision::Follow(_) => panic!("expected blocked redirect"),
    }
}
