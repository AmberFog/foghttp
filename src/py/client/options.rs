use crate::core::numeric::{
    duration_from_secs, validate_optional_usize_option, validate_usize_option,
};
use crate::errors::FogHttpError;
use crate::messages::TRUST_ENV_UNSUPPORTED;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

pub fn validate_unsupported_options(trust_env: bool) -> PyResult<()> {
    if trust_env {
        return Err(FogHttpError::new_err(TRUST_ENV_UNSUPPORTED));
    }

    Ok(())
}

#[derive(Clone, Copy)]
pub struct NumericClientOptions {
    pub max_active_requests: usize,
    pub max_active_requests_per_origin: Option<usize>,
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

pub fn validate_request_timeouts(pool_timeout: f64, total_timeout: f64) -> PyResult<()> {
    duration_from_secs("Timeouts.pool", pool_timeout).map_err(PyValueError::new_err)?;
    duration_from_secs("Timeouts.total", total_timeout).map_err(PyValueError::new_err)?;

    Ok(())
}
