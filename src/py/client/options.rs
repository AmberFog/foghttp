use crate::core::numeric::{
    duration_from_secs, validate_optional_usize_option, validate_usize_option, MAX_NUMERIC_OPTION,
};
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyInt};

pub fn extract_stream_decode_content(value: &Bound<'_, PyAny>) -> PyResult<bool> {
    value
        .cast::<PyBool>()
        .map(PyBoolMethods::is_true)
        .map_err(|_| PyTypeError::new_err("decode_content must be a bool"))
}

pub fn extract_stream_decoded_byte_limit(value: &Bound<'_, PyAny>) -> PyResult<Option<usize>> {
    if value.is_none() {
        return Ok(None);
    }
    extract_byte_limit("Limits.max_stream_decoded_bytes", value).map(Some)
}

pub fn extract_stream_decoder_memory_limit(value: &Bound<'_, PyAny>) -> PyResult<usize> {
    extract_byte_limit("Limits.max_stream_decoder_memory_bytes", value)
}

fn extract_byte_limit(name: &str, value: &Bound<'_, PyAny>) -> PyResult<usize> {
    let invalid = || {
        PyValueError::new_err(format!(
            "{name} must be an integer between 0 and {MAX_NUMERIC_OPTION}"
        ))
    };
    if value.is_instance_of::<PyBool>() || !value.is_instance_of::<PyInt>() {
        return Err(invalid());
    }
    let value = value.extract::<usize>().map_err(|_| invalid())?;
    validate_usize_option(name, value).map_err(PyValueError::new_err)
}

#[derive(Clone, Copy)]
pub struct NumericClientOptions {
    pub max_active_requests: usize,
    pub max_active_requests_per_origin: Option<usize>,
    pub max_connections: Option<usize>,
    pub max_connections_per_host: Option<usize>,
    pub max_idle_connections_per_host: usize,
    pub max_pending_requests: usize,
    pub max_response_body_size: Option<usize>,
    pub max_buffered_response_bytes: Option<usize>,
    pub idle_timeout: f64,
    pub connect_timeout: f64,
}

pub fn validate_numeric_client_options(options: NumericClientOptions) -> PyResult<()> {
    validate_usize_option("Limits.max_active_requests", options.max_active_requests)
        .map_err(PyValueError::new_err)?;
    validate_optional_usize_option(
        "Limits.max_active_requests_per_origin",
        options.max_active_requests_per_origin,
    )
    .map_err(PyValueError::new_err)?;
    validate_optional_usize_option("Limits.max_connections", options.max_connections)
        .map_err(PyValueError::new_err)?;
    validate_optional_usize_option(
        "Limits.max_connections_per_host",
        options.max_connections_per_host,
    )
    .map_err(PyValueError::new_err)?;
    validate_usize_option(
        "Limits.max_idle_connections_per_host",
        options.max_idle_connections_per_host,
    )
    .map_err(PyValueError::new_err)?;
    validate_usize_option("Limits.max_pending_requests", options.max_pending_requests)
        .map_err(PyValueError::new_err)?;
    validate_optional_usize_option(
        "Limits.max_response_body_size",
        options.max_response_body_size,
    )
    .map_err(PyValueError::new_err)?;
    validate_optional_usize_option(
        "Limits.max_buffered_response_bytes",
        options.max_buffered_response_bytes,
    )
    .map_err(PyValueError::new_err)?;
    duration_from_secs("Limits.idle_timeout", options.idle_timeout)
        .map_err(PyValueError::new_err)?;
    duration_from_secs("Timeouts.connect", options.connect_timeout)
        .map_err(PyValueError::new_err)?;

    Ok(())
}

pub fn validate_request_timeouts(
    pool_timeout: f64,
    read_timeout: f64,
    write_timeout: f64,
    total_timeout: f64,
) -> PyResult<()> {
    duration_from_secs("Timeouts.pool", pool_timeout).map_err(PyValueError::new_err)?;
    duration_from_secs("Timeouts.read", read_timeout).map_err(PyValueError::new_err)?;
    duration_from_secs("Timeouts.write", write_timeout).map_err(PyValueError::new_err)?;
    duration_from_secs("Timeouts.total", total_timeout).map_err(PyValueError::new_err)?;

    Ok(())
}

#[cfg(test)]
mod tests;
