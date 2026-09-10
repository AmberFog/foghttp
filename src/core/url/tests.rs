use super::HttpUrl;

#[test]
fn parses_and_normalizes_http_url() {
    let url = HttpUrl::parse("HTTPS://Example.COM:443/path?q=1").unwrap();

    assert_eq!(url.as_str(), "https://example.com/path?q=1");
    assert_eq!(url.scheme(), "https");
    assert_eq!(url.host(), "example.com");
    assert_eq!(url.port(), 443);
    assert_eq!(url.path(), "/path");
    assert_eq!(url.query(), "q=1");
    assert_eq!(url.origin(), "https://example.com");
}

#[test]
fn origin_preserves_normalization_without_url_secrets() {
    let cases = [
        (
            "HTTPS://Example.COM:443/path?q=1#part",
            "https://example.com",
        ),
        (
            "http://user:p%40ss@Example.COM:80/private?token=value#part", // pragma: allowlist secret
            "http://example.com",
        ),
        (
            "https://user:pass@Example.COM:8443/private", // pragma: allowlist secret
            "https://example.com:8443",
        ),
        ("http://127.0.0.1:8080/path", "http://127.0.0.1:8080"),
        ("http://[::1]:80/path", "http://[::1]"),
        (
            "https://user:pass@[2001:0DB8::1]:8443/private?token=value", // pragma: allowlist secret
            "https://[2001:db8::1]:8443",
        ),
        (
            "https://b\u{00fc}cher.example/path",
            "https://xn--bcher-kva.example",
        ),
        ("http://example.com:0/path", "http://example.com:0"),
    ];

    for (input, expected) in cases {
        assert_eq!(HttpUrl::parse(input).unwrap().origin(), expected);
    }
}

#[test]
fn joins_relative_locations() {
    let url = HttpUrl::parse("https://example.com/users/current/profile").unwrap();

    assert_eq!(
        url.join("../settings").unwrap().as_str(),
        "https://example.com/users/settings",
    );
}

#[test]
fn joins_scheme_relative_locations() {
    let url = HttpUrl::parse("https://example.com/users").unwrap();

    assert_eq!(
        url.join("//api.example.com/v1").unwrap().as_str(),
        "https://api.example.com/v1",
    );
}

#[test]
fn compares_default_port_origin() {
    let base = HttpUrl::parse("https://example.com").unwrap();
    let other = HttpUrl::parse("https://example.com:443/path").unwrap();

    assert!(base.is_same_origin(&other));
}

#[test]
fn rejects_non_http_schemes() {
    let error = HttpUrl::parse("ftp://example.com").unwrap_err();

    assert_eq!(error, "URL scheme must be http or https");
}
