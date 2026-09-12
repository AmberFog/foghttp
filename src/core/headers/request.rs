use super::HeaderPairs;
use hyper::header::{HeaderMap, HeaderName, HeaderValue};
use hyper::http::Error;
use std::str::FromStr;

pub fn request_headers(headers: HeaderPairs) -> Result<HeaderMap, Error> {
    let mut header_map = HeaderMap::new();

    for (name, value) in headers {
        let header_name = HeaderName::from_str(&name)?;
        let header_value = HeaderValue::from_str(&value)?;
        header_map.append(header_name, header_value);
    }

    Ok(header_map)
}
