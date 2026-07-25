use crate::core::client::{
    connection_acquire_timeout_from_error, request_write_timeout_from_error,
};
use crate::core::policy::{PolicyError, SsrfViolation};
use crate::core::telemetry::TelemetryErrorType;
use crate::errors::{transport_error_message, FogHttpError, FogHttpNetworkError, FogHttpSsrfError};
use crate::messages::CONNECTION_ACQUIRE_TIMEOUT;
use crate::py::client::timeout_diagnostics::{
    connection_acquire_timeout_error, write_timeout_error,
};
use hyper::Error as HyperError;
use pyo3::prelude::*;
use std::error::Error;

pub(super) fn policy_error(error: &PolicyError) -> PyErr {
    if let PolicyError::SsrfViolation(violation) = error {
        return ssrf_error(violation);
    }
    FogHttpError::new_err(error.to_string())
}

pub(super) fn transport_error(error: &(dyn Error + 'static)) -> PyErr {
    match transport_error_kind(error) {
        TransportErrorKind::WriteTimeout => write_timeout_error(
            request_write_timeout_from_error(error)
                .expect("write timeout kind must retain its source"),
        ),
        TransportErrorKind::PoolTimeout => {
            let timeout = connection_acquire_timeout_from_error(error)
                .expect("pool timeout kind must retain its source");
            connection_acquire_timeout_error(
                CONNECTION_ACQUIRE_TIMEOUT,
                timeout.elapsed(),
                timeout.timeout(),
                timeout.origin(),
                timeout.redirect_hop(),
            )
        }
        TransportErrorKind::Ssrf => ssrf_error(
            ssrf_violation_from_error(error).expect("SSRF error kind must retain its source"),
        ),
        TransportErrorKind::Request => FogHttpError::new_err(transport_error_message(error)),
        TransportErrorKind::Network => FogHttpNetworkError::new_err(transport_error_message(error)),
    }
}

pub(super) fn transport_telemetry_error_type(error: &(dyn Error + 'static)) -> TelemetryErrorType {
    match transport_error_kind(error) {
        TransportErrorKind::WriteTimeout => TelemetryErrorType::WriteTimeout,
        TransportErrorKind::PoolTimeout => TelemetryErrorType::PoolTimeout,
        TransportErrorKind::Ssrf => TelemetryErrorType::SsrfError,
        TransportErrorKind::Request => TelemetryErrorType::RequestError,
        TransportErrorKind::Network => TelemetryErrorType::NetworkError,
    }
}

fn ssrf_error(violation: &SsrfViolation) -> PyErr {
    FogHttpSsrfError::new_err((
        violation.to_string(),
        violation.reason().as_code().to_owned(),
    ))
}

pub(super) fn is_retryable_network_error(error: &(dyn Error + 'static)) -> bool {
    transport_error_kind(error) == TransportErrorKind::Network
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum TransportErrorKind {
    WriteTimeout,
    PoolTimeout,
    Ssrf,
    Request,
    Network,
}

fn transport_error_kind(error: &(dyn Error + 'static)) -> TransportErrorKind {
    if request_write_timeout_from_error(error).is_some() {
        TransportErrorKind::WriteTimeout
    } else if connection_acquire_timeout_from_error(error).is_some() {
        TransportErrorKind::PoolTimeout
    } else if ssrf_violation_from_error(error).is_some() {
        TransportErrorKind::Ssrf
    } else if error_chain_contains_user_error(error) {
        TransportErrorKind::Request
    } else {
        TransportErrorKind::Network
    }
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
