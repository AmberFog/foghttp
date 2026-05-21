use super::response_headers;
use hyper::header::{HeaderMap, HeaderName, HeaderValue};

#[test]
fn response_headers_preserve_obs_text_values_as_latin_1() {
    let mut headers = HeaderMap::new();
    headers.append(
        HeaderName::from_static("x-obs-text"),
        HeaderValue::from_bytes(b"value-\xe9").unwrap(),
    );

    assert_eq!(
        response_headers(&headers),
        vec![("x-obs-text".to_owned(), "value-\u{e9}".to_owned())],
    );
}

#[test]
fn response_headers_preserve_repeated_mixed_ascii_and_obs_text_values() {
    let mut headers = HeaderMap::new();
    headers.append(
        HeaderName::from_static("x-repeat"),
        HeaderValue::from_static("ascii"),
    );
    headers.append(
        HeaderName::from_static("x-repeat"),
        HeaderValue::from_bytes(b"repeat-\xe9").unwrap(),
    );

    assert_eq!(
        response_headers(&headers),
        vec![
            ("x-repeat".to_owned(), "ascii".to_owned()),
            ("x-repeat".to_owned(), "repeat-\u{e9}".to_owned()),
        ],
    );
}
