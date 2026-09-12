use pyo3::prelude::*;

pub(crate) const RETRY_TRACE_ATTRIBUTE: &str = "_foghttp_retry_trace";

#[derive(Clone)]
#[pyclass(skip_from_py_object)]
pub struct RawRetryAttempt {
    #[pyo3(get)]
    pub attempt: usize,
    #[pyo3(get)]
    pub method: String,
    #[pyo3(get)]
    pub origin: String,
    #[pyo3(get)]
    pub redirect_hop: usize,
    #[pyo3(get)]
    pub status_code: Option<u16>,
    #[pyo3(get)]
    pub error_type: Option<String>,
    #[pyo3(get)]
    pub decision: Option<String>,
    #[pyo3(get)]
    pub reason: Option<String>,
    #[pyo3(get)]
    pub backoff: f64,
    #[pyo3(get)]
    pub decision_elapsed: Option<f64>,
    #[pyo3(get)]
    pub completed_elapsed: f64,
    pub(crate) completion: RetryAttemptCompletion,
}

impl RawRetryAttempt {
    fn has_valid_decision_state(&self) -> bool {
        self.decision.is_some() == self.reason.is_some()
            && self.decision.is_some() == self.decision_elapsed.is_some()
            && self
                .decision_elapsed
                .is_none_or(|elapsed| elapsed <= self.completed_elapsed)
            && (self.completion == RetryAttemptCompletion::Complete || self.decision.is_some())
    }
}

#[derive(Clone)]
#[pyclass(skip_from_py_object)]
pub struct RawRetryTrace {
    attempts: Vec<RawRetryAttempt>,
    #[pyo3(get)]
    pub outcome: String,
    #[pyo3(get)]
    pub status_code: Option<u16>,
    #[pyo3(get)]
    pub elapsed: f64,
    #[pyo3(get)]
    pub terminal_error_on_last_attempt: bool,
}

#[pymethods]
impl RawRetryTrace {
    #[getter]
    fn attempts(&self) -> Vec<RawRetryAttempt> {
        self.attempts.clone()
    }
}

#[derive(Clone, Copy)]
pub(crate) enum RetryTraceOutcome {
    Response,
    Error,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum RetryAttemptCompletion {
    Pending,
    Complete,
}

#[derive(Clone, Copy)]
pub(crate) struct RetryResponseObservation {
    pub status_code: u16,
    pub redirect_hop: usize,
}

impl RetryTraceOutcome {
    fn as_str(self) -> &'static str {
        match self {
            Self::Response => "response",
            Self::Error => "error",
        }
    }
}

pub(crate) struct RetryTraceRecorder {
    attempts: Option<Vec<RawRetryAttempt>>,
    observed_response: Option<RetryResponseObservation>,
}

impl RetryTraceRecorder {
    pub(crate) fn disabled() -> Self {
        Self {
            attempts: None,
            observed_response: None,
        }
    }

    pub(crate) fn enabled() -> Self {
        Self {
            attempts: Some(Vec::new()),
            observed_response: None,
        }
    }

    pub(crate) fn is_enabled(&self) -> bool {
        self.attempts.is_some()
    }

    pub(crate) fn begin_transport_hop(&mut self) {
        if self.is_enabled() {
            self.observed_response = None;
        }
    }

    pub(crate) fn observe_response(&mut self, status_code: u16, redirect_hop: usize) {
        if self.is_enabled() {
            self.observed_response = Some(RetryResponseObservation {
                status_code,
                redirect_hop,
            });
        }
    }

    pub(crate) fn observed_response(&self) -> Option<RetryResponseObservation> {
        self.observed_response
    }

    pub(crate) fn record(&mut self, attempt: RawRetryAttempt) {
        if let Some(attempts) = self.attempts.as_mut() {
            debug_assert!(
                attempt.has_valid_decision_state(),
                "retry decision fields and timing must form a valid attempt state",
            );
            debug_assert!(
                attempts
                    .last()
                    .is_none_or(|recorded| recorded.attempt < attempt.attempt),
                "retry trace attempts must be recorded once in order",
            );
            attempts.push(attempt);
        }
    }

    pub(crate) fn finish(
        &mut self,
        terminal_attempt: RawRetryAttempt,
        outcome: RetryTraceOutcome,
        status_code: Option<u16>,
        elapsed: f64,
    ) -> Option<RawRetryTrace> {
        debug_assert_eq!(
            terminal_attempt.completion,
            RetryAttemptCompletion::Complete,
        );
        debug_assert!(
            terminal_attempt.has_valid_decision_state(),
            "terminal retry attempt must not contain an incomplete decision state",
        );
        let mut attempts = self.attempts.take()?;
        let terminal_error_on_last_attempt = match attempts.last_mut() {
            Some(attempt) if attempt.attempt == terminal_attempt.attempt => {
                if attempt.completion == RetryAttemptCompletion::Complete {
                    false
                } else {
                    attempt.status_code = terminal_attempt.status_code.or(attempt.status_code);
                    attempt.redirect_hop = terminal_attempt.redirect_hop;
                    attempt.completed_elapsed = terminal_attempt.completed_elapsed;
                    attempt.completion = RetryAttemptCompletion::Complete;
                    matches!(outcome, RetryTraceOutcome::Error)
                }
            }
            _ => {
                attempts.push(terminal_attempt);
                matches!(outcome, RetryTraceOutcome::Error)
            }
        };
        debug_assert!(
            attempts
                .iter()
                .all(RawRetryAttempt::has_valid_decision_state),
            "completed retry trace must preserve attempt decision invariants",
        );
        Some(RawRetryTrace {
            attempts,
            outcome: outcome.as_str().to_owned(),
            status_code,
            elapsed,
            terminal_error_on_last_attempt,
        })
    }
}

pub(crate) fn attach_retry_trace(error: PyErr, trace: Option<RawRetryTrace>) -> PyErr {
    let Some(trace) = trace else {
        return error;
    };

    Python::attach(|py| {
        let result = Py::new(py, trace)
            .and_then(|trace| error.value(py).setattr(RETRY_TRACE_ATTRIBUTE, trace));
        if let Err(attach_error) = result {
            attach_error.write_unraisable(py, Some(error.value(py)));
        }
    });
    error
}

#[cfg(test)]
mod tests;
