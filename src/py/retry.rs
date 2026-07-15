use pyo3::prelude::*;
use pyo3::types::PyTuple;

pub(crate) const RETRY_DECISIONS_ATTRIBUTE: &str = "_foghttp_retry_decisions";

#[derive(Clone)]
#[pyclass(skip_from_py_object)]
pub struct RawRetryDecision {
    #[pyo3(get)]
    pub attempt: usize,
    #[pyo3(get)]
    pub method: String,
    #[pyo3(get)]
    pub origin: String,
    #[pyo3(get)]
    pub status_code: Option<u16>,
    #[pyo3(get)]
    pub error_type: Option<String>,
    #[pyo3(get)]
    pub decision: String,
    #[pyo3(get)]
    pub reason: String,
    #[pyo3(get)]
    pub backoff: f64,
    #[pyo3(get)]
    pub elapsed: f64,
}

pub(crate) fn attach_retry_decisions(error: PyErr, decisions: Vec<RawRetryDecision>) -> PyErr {
    if decisions.is_empty() {
        return error;
    }

    Python::attach(|py| {
        let decisions = decisions
            .into_iter()
            .map(|decision| Py::new(py, decision))
            .collect::<PyResult<Vec<_>>>()?;
        let decisions = PyTuple::new(py, decisions)?;
        error
            .value(py)
            .setattr(RETRY_DECISIONS_ATTRIBUTE, decisions)
    })
    .ok();
    error
}
