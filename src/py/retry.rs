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
    pub elapsed: f64,
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
}

impl RetryTraceRecorder {
    pub(crate) fn disabled() -> Self {
        Self { attempts: None }
    }

    pub(crate) fn enabled() -> Self {
        Self {
            attempts: Some(Vec::new()),
        }
    }

    pub(crate) fn is_enabled(&self) -> bool {
        self.attempts.is_some()
    }

    pub(crate) fn record(&mut self, attempt: RawRetryAttempt) {
        if let Some(attempts) = self.attempts.as_mut() {
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
        let mut attempts = self.attempts.take()?;
        if attempts
            .last()
            .is_none_or(|attempt| attempt.attempt != terminal_attempt.attempt)
        {
            attempts.push(terminal_attempt);
        }
        Some(RawRetryTrace {
            attempts,
            outcome: outcome.as_str().to_owned(),
            status_code,
            elapsed,
        })
    }
}

pub(crate) fn attach_retry_trace(error: PyErr, trace: Option<RawRetryTrace>) -> PyErr {
    let Some(trace) = trace else {
        return error;
    };

    Python::attach(|py| {
        let trace = Py::new(py, trace)?;
        error.value(py).setattr(RETRY_TRACE_ATTRIBUTE, trace)
    })
    .ok();
    error
}

#[cfg(test)]
mod tests {
    use super::{RawRetryAttempt, RetryTraceOutcome, RetryTraceRecorder};

    fn attempt(attempt: usize, decision: Option<&str>) -> RawRetryAttempt {
        RawRetryAttempt {
            attempt,
            method: "GET".to_owned(),
            origin: "https://example.test".to_owned(),
            redirect_hop: 0,
            status_code: Some(503),
            error_type: None,
            decision: decision.map(str::to_owned),
            reason: decision.map(|_| "status".to_owned()),
            backoff: 0.0,
            elapsed: f64::from(u32::try_from(attempt).expect("test attempt fits in u32")),
        }
    }

    #[test]
    fn disabled_recorder_does_not_create_a_trace() {
        let mut recorder = RetryTraceRecorder::disabled();

        recorder.record(attempt(1, Some("retry")));
        let trace = recorder.finish(
            attempt(2, None),
            RetryTraceOutcome::Response,
            Some(200),
            2.0,
        );

        assert!(trace.is_none());
    }

    #[test]
    fn terminal_attempt_is_appended_after_a_retry() {
        let mut recorder = RetryTraceRecorder::enabled();
        recorder.record(attempt(1, Some("retry")));

        let trace = recorder
            .finish(
                attempt(2, None),
                RetryTraceOutcome::Response,
                Some(200),
                2.0,
            )
            .expect("enabled recorder must produce a trace");

        assert_eq!(trace.attempts.len(), 2);
        assert_eq!(trace.attempts[1].attempt, 2);
        assert_eq!(trace.outcome, "response");
        assert_eq!(trace.status_code, Some(200));
    }

    #[test]
    fn terminal_stop_does_not_duplicate_the_attempt() {
        let mut recorder = RetryTraceRecorder::enabled();
        recorder.record(attempt(1, Some("stop")));

        let trace = recorder
            .finish(attempt(1, None), RetryTraceOutcome::Error, None, 1.0)
            .expect("enabled recorder must produce a trace");

        assert_eq!(trace.attempts.len(), 1);
        assert_eq!(trace.outcome, "error");
    }
}
