use pyo3::prelude::*;
use pyo3::types::PyBytes;

use crate::core::headers::HeaderPairs;

#[pyclass(skip_from_py_object)]
#[derive(Clone)]
pub struct RawRequestInfo {
    #[pyo3(get)]
    pub method: String,
    #[pyo3(get)]
    pub url: String,
    #[pyo3(get)]
    pub headers: HeaderPairs,
}

#[pyclass(skip_from_py_object)]
#[derive(Clone)]
pub struct RawResponse {
    #[pyo3(get)]
    pub status_code: u16,
    #[pyo3(get)]
    pub headers: HeaderPairs,
    pub content: Vec<u8>,
    #[pyo3(get)]
    pub url: String,
    #[pyo3(get)]
    pub request: RawRequestInfo,
    #[pyo3(get)]
    pub http_version: String,
    #[pyo3(get)]
    pub elapsed: f64,
    pub history: Vec<RawResponse>,
}

#[pymethods]
impl RawResponse {
    #[getter]
    fn content<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.content)
    }

    #[getter]
    fn history(&self) -> Vec<Self> {
        self.history.clone()
    }
}
