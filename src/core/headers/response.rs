use super::HeaderPairs;
use hyper::header::{HeaderMap, HeaderValue};

pub fn response_headers(headers: &HeaderMap) -> HeaderPairs {
    let mut mapped = Vec::new();

    for (name, value) in headers {
        mapped.push((
            name.as_str().to_owned(),
            response_header_value_as_latin_1(value),
        ));
    }

    mapped
}

fn response_header_value_as_latin_1(value: &HeaderValue) -> String {
    value.as_bytes().iter().copied().map(char::from).collect()
}
