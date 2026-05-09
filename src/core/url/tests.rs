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
