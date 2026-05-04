use pyo3::prelude::*;
use pyo3::types::PyBytes;
use std::collections::HashMap;

#[pyclass]
pub struct RawResponse {
    #[pyo3(get)]
    pub status_code: u16,
    #[pyo3(get)]
    pub headers: HashMap<String, String>,
    pub content: Vec<u8>,
    #[pyo3(get)]
    pub url: String,
    #[pyo3(get)]
    pub http_version: String,
    #[pyo3(get)]
    pub elapsed: f64,
}

#[pymethods]
impl RawResponse {
    #[getter]
    fn content<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.content)
    }
}
