use crate::core::client::{
    connection_acquire_timeout_from_error, request_write_timeout_from_error,
};
use crate::core::policy::{PolicyError, SsrfViolation};
use crate::errors::{transport_error_message, FogHttpError, FogHttpNetworkError};
use crate::messages::CONNECTION_ACQUIRE_TIMEOUT;
use crate::py::client::timeout_diagnostics::{
    connection_acquire_timeout_error, write_timeout_error,
};
use hyper::Error as HyperError;
use pyo3::prelude::*;
use std::error::Error;

pub(super) fn policy_error(error: &PolicyError) -> PyErr {
    FogHttpError::new_err(error.to_string())
}

pub(super) fn transport_error(error: &(dyn Error + 'static)) -> PyErr {
    if let Some(timeout) = request_write_timeout_from_error(error) {
        return write_timeout_error(timeout);
    }
    if let Some(timeout) = connection_acquire_timeout_from_error(error) {
        return connection_acquire_timeout_error(
            CONNECTION_ACQUIRE_TIMEOUT,
            timeout.elapsed(),
            timeout.timeout(),
            timeout.origin(),
            timeout.redirect_hop(),
        );
    }
    if let Some(violation) = ssrf_violation_from_error(error) {
        return FogHttpError::new_err(violation.to_string());
    }
    if error_chain_contains_user_error(error) {
        return FogHttpError::new_err(transport_error_message(error));
    }
    FogHttpNetworkError::new_err(transport_error_message(error))
}

pub(super) fn is_retryable_network_error(error: &(dyn Error + 'static)) -> bool {
    request_write_timeout_from_error(error).is_none()
        && connection_acquire_timeout_from_error(error).is_none()
        && ssrf_violation_from_error(error).is_none()
        && !error_chain_contains_user_error(error)
}

fn ssrf_violation_from_error<'a>(
    mut error: &'a (dyn Error + 'static),
) -> Option<&'a SsrfViolation> {
    loop {
        if let Some(violation) = error.downcast_ref::<SsrfViolation>() {
            return Some(violation);
        }
        error = error.source()?;
    }
}

fn error_chain_contains_user_error(mut error: &(dyn Error + 'static)) -> bool {
    loop {
        if error
            .downcast_ref::<HyperError>()
            .is_some_and(HyperError::is_user)
        {
            return true;
        }
        let Some(source) = error.source() else {
            return false;
        };
        error = source;
    }
}
