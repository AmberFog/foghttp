use crate::core::client::RequestWriteTimeout;
use crate::core::numeric;
use crate::errors::{
    FogHttpPoolTimeoutError, FogHttpReadTimeoutError, FogHttpTimeoutError, FogHttpWriteTimeoutError,
};
use crate::messages::REQUEST_BODY_WRITE_TIMEOUT;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::time::{Duration, Instant};

#[derive(Clone, Copy)]
pub enum TimeoutPhase {
    ConnectionAcquire,
    PoolAcquire,
    RequestBody,
    ResponseBody,
    ResponseHeaders,
}

impl TimeoutPhase {
    fn as_str(self) -> &'static str {
        match self {
            Self::ConnectionAcquire => "connection_acquire",
            Self::PoolAcquire => "pool_acquire",
            Self::RequestBody => "request_body",
            Self::ResponseBody => "response_body",
            Self::ResponseHeaders => "response_headers",
        }
    }
}

pub struct TimeoutContext<'a> {
    phase: TimeoutPhase,
    started: Instant,
    timeout: f64,
    origin: &'a str,
    redirect_hop: usize,
}

impl<'a> TimeoutContext<'a> {
    pub fn new(
        phase: TimeoutPhase,
        started: Instant,
        timeout: f64,
        origin: &'a str,
        redirect_hop: usize,
    ) -> Self {
        Self {
            phase,
            started,
            timeout,
            origin,
            redirect_hop,
        }
    }

    fn args(&self, message: &'static str) -> (String, String, f64, f64, String, usize) {
        (
            message.to_owned(),
            self.phase.as_str().to_owned(),
            self.started.elapsed().as_secs_f64(),
            self.timeout,
            self.origin.to_owned(),
            self.redirect_hop,
        )
    }
}

pub fn timeout_error(context: &TimeoutContext<'_>, message: &'static str) -> PyErr {
    FogHttpTimeoutError::new_err(context.args(message))
}

pub fn pool_timeout_error(context: &TimeoutContext<'_>, message: &'static str) -> PyErr {
    FogHttpPoolTimeoutError::new_err(context.args(message))
}

pub fn connection_acquire_timeout_error(
    message: &'static str,
    elapsed: f64,
    timeout: f64,
    origin: &str,
    redirect_hop: usize,
) -> PyErr {
    FogHttpPoolTimeoutError::new_err((
        message.to_owned(),
        TimeoutPhase::ConnectionAcquire.as_str().to_owned(),
        elapsed,
        timeout,
        origin.to_owned(),
        redirect_hop,
    ))
}

pub fn read_timeout_error(context: &TimeoutContext<'_>, message: &'static str) -> PyErr {
    FogHttpReadTimeoutError::new_err(context.args(message))
}

pub fn write_timeout_error(timeout: &RequestWriteTimeout) -> PyErr {
    FogHttpWriteTimeoutError::new_err((
        REQUEST_BODY_WRITE_TIMEOUT.to_owned(),
        TimeoutPhase::RequestBody.as_str().to_owned(),
        timeout.elapsed(),
        timeout.timeout(),
        timeout.origin().to_owned(),
        timeout.redirect_hop(),
    ))
}

pub fn remaining_duration(name: &str, context: &TimeoutContext<'_>) -> PyResult<Duration> {
    numeric::remaining_duration(name, context.timeout, context.started)
        .map_err(PyValueError::new_err)
}
