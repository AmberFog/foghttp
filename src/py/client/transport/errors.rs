use crate::core::client::request_write_timeout_from_error;
use crate::errors::{transport_error_message, FogHttpError};
use crate::py::client::timeout_diagnostics::write_timeout_error;
use pyo3::prelude::*;
use std::error::Error;

pub(super) fn transport_error(error: &(dyn Error + 'static)) -> PyErr {
    if let Some(timeout) = request_write_timeout_from_error(error) {
        return write_timeout_error(timeout);
    }
    FogHttpError::new_err(transport_error_message(error))
}
