use crate::core::response::BufferedBodyReservation;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

use crate::core::headers::HeaderPairs;

pub(crate) struct RawResponseParts {
    pub status_code: u16,
    pub headers: HeaderPairs,
    pub content: Vec<u8>,
    pub url: String,
    pub request: RawRequestInfo,
    pub http_version: String,
    pub elapsed: f64,
    pub history: Vec<RawResponse>,
    pub body_reservation: Option<BufferedBodyReservation>,
}

#[pyclass(skip_from_py_object)]
pub struct RawRequestInfo {
    #[pyo3(get)]
    pub method: String,
    #[pyo3(get)]
    pub url: String,
    #[pyo3(get)]
    pub headers: HeaderPairs,
}

impl Clone for RawRequestInfo {
    fn clone(&self) -> Self {
        Self {
            method: self.method.clone(),
            url: self.url.clone(),
            headers: self.headers.clone(),
        }
    }
}

#[pyclass(skip_from_py_object)]
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
    body_reservation: Option<BufferedBodyReservation>,
}

impl Clone for RawResponse {
    fn clone(&self) -> Self {
        Self {
            status_code: self.status_code,
            headers: self.headers.clone(),
            content: self.content.clone(),
            url: self.url.clone(),
            request: self.request.clone(),
            http_version: self.http_version.clone(),
            elapsed: self.elapsed,
            history: self.history.clone(),
            body_reservation: None,
        }
    }
}

impl RawResponse {
    pub(crate) fn from_parts(parts: RawResponseParts) -> Self {
        Self {
            status_code: parts.status_code,
            headers: parts.headers,
            content: parts.content,
            url: parts.url,
            request: parts.request,
            http_version: parts.http_version,
            elapsed: parts.elapsed,
            history: parts.history,
            body_reservation: parts.body_reservation,
        }
    }

    fn release_body_reservations(&mut self) {
        self.body_reservation.take();
        for response in &mut self.history {
            response.release_body_reservations();
        }
    }
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

    fn release_buffered_body_reservations(&mut self) {
        self.release_body_reservations();
    }
}
