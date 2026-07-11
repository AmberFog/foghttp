use super::{build_multi_thread_runtime, shared_runtime_workers};
use crate::errors::FogHttpError;
use crate::py::client::process::{current_process_id, ProcessId};
use pyo3::exceptions::PyAttributeError;
use pyo3::prelude::*;
use std::sync::Arc;
use tokio::runtime::Runtime;

const SHARED_RUNTIME_ATTRIBUTE: &str = "_shared_runtime_state";

#[pyclass(module = "foghttp._foghttp")]
struct SharedRuntimeState {
    process_id: ProcessId,
    runtime: Option<Arc<Runtime>>,
}

impl Drop for SharedRuntimeState {
    fn drop(&mut self) {
        // A process-wide runtime lives until process teardown. Dropping inherited
        // Tokio state after fork can wait on worker threads that no longer exist.
        std::mem::forget(self.runtime.take());
    }
}

pub(super) fn shared_runtime(py: Python<'_>) -> PyResult<Arc<Runtime>> {
    let process_id = current_process_id();
    let module = py.import("foghttp._foghttp")?;

    match module.getattr(SHARED_RUNTIME_ATTRIBUTE) {
        Ok(state) => {
            let mut state = state.cast::<SharedRuntimeState>()?.borrow_mut();
            if state.process_id == process_id {
                return state
                    .runtime
                    .as_ref()
                    .map(Arc::clone)
                    .ok_or_else(|| FogHttpError::new_err("shared runtime state is empty"));
            }

            let runtime = build_shared_runtime()?;
            let inherited_runtime = state.runtime.replace(Arc::clone(&runtime));
            state.process_id = process_id;
            std::mem::forget(inherited_runtime);
            return Ok(runtime);
        }
        Err(error) if error.is_instance_of::<PyAttributeError>(py) => {}
        Err(error) => return Err(error),
    }

    let runtime = build_shared_runtime()?;
    let state = Bound::new(
        py,
        SharedRuntimeState {
            process_id,
            runtime: Some(Arc::clone(&runtime)),
        },
    )?;
    module.setattr(SHARED_RUNTIME_ATTRIBUTE, state)?;
    Ok(runtime)
}

fn build_shared_runtime() -> PyResult<Arc<Runtime>> {
    let worker_threads = shared_runtime_workers();
    build_multi_thread_runtime(worker_threads).map(Arc::new)
}
