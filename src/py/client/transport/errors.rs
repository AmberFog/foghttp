use crate::core::client::{
    connection_acquire_timeout_from_error, request_write_timeout_from_error,
};
use crate::errors::{transport_error_message, FogHttpError};
use crate::messages::CONNECTION_ACQUIRE_TIMEOUT;
use crate::py::client::timeout_diagnostics::{
    connection_acquire_timeout_error, write_timeout_error,
};
use pyo3::prelude::*;
use std::error::Error;

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
    FogHttpError::new_err(transport_error_message(error))
}
