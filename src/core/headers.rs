use crate::errors::FogHttpError;
use hyper::header::{HeaderMap, HeaderName, HeaderValue};
use pyo3::prelude::*;
use std::collections::HashMap;
use std::str::FromStr;

pub fn request_headers(headers: HashMap<String, String>) -> PyResult<HeaderMap> {
    let mut header_map = HeaderMap::new();

    for (name, value) in headers {
        let header_name =
            HeaderName::from_str(&name).map_err(|err| FogHttpError::new_err(err.to_string()))?;
        let header_value =
            HeaderValue::from_str(&value).map_err(|err| FogHttpError::new_err(err.to_string()))?;
        header_map.insert(header_name, header_value);
    }

    Ok(header_map)
}

pub fn response_headers(headers: &HeaderMap) -> HashMap<String, String> {
    let mut mapped = HashMap::new();

    for (name, value) in headers {
        if let Ok(value) = value.to_str() {
            mapped.insert(name.as_str().to_ascii_lowercase(), value.to_owned());
        }
    }

    mapped
}
