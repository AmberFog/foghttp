use super::HeaderPairs;
use crate::errors::FogHttpError;
use hyper::header::{HeaderMap, HeaderName, HeaderValue};
use pyo3::prelude::*;
use std::str::FromStr;

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
