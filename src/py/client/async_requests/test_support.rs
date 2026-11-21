use super::active::{ActiveAsyncRequest, RequestCompletion};
use super::callback::PythonFutureCancellation;
use super::AsyncRequestRegistry;
use crate::core::metrics::Metrics;
use pyo3::prelude::*;
use std::sync::Arc;
use tokio::task::AbortHandle;

pub(crate) fn register_request(
    py: Python<'_>,
    registry: &AsyncRequestRegistry,
    abort_handle: AbortHandle,
    loop_: &Py<PyAny>,
    future: &Py<PyAny>,
    metrics: Arc<Metrics>,
) -> PyResult<RequestCompletion> {
    let request_id = registry.next_request_id();
    let completion = RequestCompletion::default();
    registry.insert(
        request_id,
        ActiveAsyncRequest::new(
            abort_handle,
            loop_.clone_ref(py),
            future.clone_ref(py),
            metrics,
            None,
            completion.clone(),
        ),
    );
    let callback = Py::new(
        py,
        PythonFutureCancellation::new(request_id, registry.clone()),
    )?;
    future
        .bind(py)
        .call_method1("add_done_callback", (callback,))?;
    Ok(completion)
}
