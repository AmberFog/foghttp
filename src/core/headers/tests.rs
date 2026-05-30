use super::{request_headers, response_headers};
use hyper::header::{HeaderMap, HeaderName, HeaderValue};

#[test]
fn request_headers_preserve_repeated_values() {
    let headers = request_headers(vec![
        ("x-repeat".to_owned(), "first".to_owned()),
        ("x-repeat".to_owned(), "second".to_owned()),
    ])
    .expect("valid request headers");

    let values = headers
        .get_all("x-repeat")
        .iter()
        .map(|value| value.to_str().expect("valid ascii header value"))
        .collect::<Vec<_>>();

    assert_eq!(values, vec!["first", "second"]);
}

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
