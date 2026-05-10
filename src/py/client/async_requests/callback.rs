use super::registry::AsyncRequestRegistry;
use pyo3::prelude::*;
use pyo3::types::PyAny;

#[pyclass]
pub(super) struct PythonFutureCancellation {
    request_id: u64,
    registry: AsyncRequestRegistry,
}

impl PythonFutureCancellation {
    pub(super) fn new(request_id: u64, registry: AsyncRequestRegistry) -> Self {
        Self {
            request_id,
            registry,
        }
    }
}

#[pymethods]
impl PythonFutureCancellation {
    fn __call__(&self, future: &Bound<'_, PyAny>) -> PyResult<()> {
        if future.call_method0("cancelled")?.extract()? {
            self.registry.abort_request(self.request_id);
        }
        Ok(())
    }
}
