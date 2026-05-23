use super::state::StreamState;
use pyo3::prelude::*;
use pyo3::types::PyAny;
use tokio::task::AbortHandle;

#[pyclass]
pub(super) struct PythonStreamReadCancellation {
    state: StreamState,
    abort_handle: AbortHandle,
}

impl PythonStreamReadCancellation {
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
}

#[pymethods]
impl PythonStreamReadCancellation {
    fn __call__(&self, future: &Bound<'_, PyAny>) -> PyResult<()> {
        if future.call_method0("cancelled")?.extract()? {
            self.cancel_read();
        }
        Ok(())
    }
}
