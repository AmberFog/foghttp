use super::state::StreamState;
use pyo3::prelude::*;
use pyo3::types::PyAny;
use tokio::task::AbortHandle;

#[pyclass]
pub(super) struct PythonStreamReadCallback {
    state: StreamState,
    abort_handle: AbortHandle,
}

impl PythonStreamReadCallback {
    pub(super) fn new(state: StreamState, abort_handle: AbortHandle) -> Self {
        Self {
            state,
            abort_handle,
        }
    }

    fn cancel_read(&self) {
        self.abort_handle.abort();
        self.state.abort();
    }

    fn complete_read(&self) {
        self.state.finish_read_delivery();
    }
}

#[pymethods]
impl PythonStreamReadCallback {
    fn __call__(&self, future: &Bound<'_, PyAny>) -> PyResult<()> {
        if future.call_method0("cancelled")?.extract()? {
            self.cancel_read();
        } else {
            self.complete_read();
        }
        Ok(())
    }
}
