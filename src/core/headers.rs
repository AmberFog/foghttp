use crate::errors::FogHttpError;
use hyper::header::{HeaderMap, HeaderName, HeaderValue};
use pyo3::prelude::*;
use std::str::FromStr;

#[cfg(test)]
mod tests;

pub type HeaderPairs = Vec<(String, String)>;

pub fn request_headers(headers: HeaderPairs) -> PyResult<HeaderMap> {
    let mut header_map = HeaderMap::new();

    for (name, value) in headers {
        let header_name =
            HeaderName::from_str(&name).map_err(|err| FogHttpError::new_err(err.to_string()))?;
        let header_value =
            HeaderValue::from_str(&value).map_err(|err| FogHttpError::new_err(err.to_string()))?;
        header_map.append(header_name, header_value);
    }

    Ok(header_map)
}

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
