use super::active::{ActiveAsyncRequest, RequestCompletion};
use super::callback::PythonFutureCancellation;
use super::registry::AsyncRequestRegistry;
use crate::core::client::HyperClient;
use crate::core::metrics::Metrics;
use crate::py::client::acquire::AcquireGate;
use crate::py::client::future::complete_python_future;
use crate::py::client::transport::{send_request, TransportRequest};
use pyo3::prelude::*;
use pyo3::types::PyAny;
use std::sync::Arc;
use tokio::runtime::Runtime;

pub struct AsyncRequestSpawn {
    pub acquire_gate: AcquireGate,
    pub client: HyperClient,
    pub metrics: Arc<Metrics>,
    pub pool_timeout: f64,
    pub request: TransportRequest,
}

pub fn spawn_async_request(
    py: Python<'_>,
    runtime: &Runtime,
    registry: &AsyncRequestRegistry,
    spawn: AsyncRequestSpawn,
) -> PyResult<Py<PyAny>> {
    let AsyncRequestSpawn {
        acquire_gate,
        client,
        metrics,
        pool_timeout,
        request,
    } = spawn;
    let loop_ = py
        .import("asyncio")?
        .call_method0("get_running_loop")?
        .unbind();
    let future = loop_.bind(py).call_method0("create_future")?.unbind();
    let request_id = registry.next_request_id();
    let completion = RequestCompletion::default();

    let task_loop = loop_.clone_ref(py);
    let task_future = future.clone_ref(py);
    let task_registry = registry.clone();
    let task_metrics = Arc::clone(&metrics);
    let task_completion = completion.clone();

    metrics.request_started();
    let handle = runtime.spawn(async move {
        let result = send_request(client, acquire_gate, pool_timeout, request).await;
        if task_completion.finish() {
            task_registry.remove(request_id);
            task_metrics.request_finished(result.is_err());
            complete_python_future(&task_loop, &task_future, result);
        }
    });

    registry.insert(
        request_id,
        ActiveAsyncRequest::new(
            handle.abort_handle(),
            loop_.clone_ref(py),
            future.clone_ref(py),
            metrics,
            completion.clone(),
        ),
    );
    if completion.is_finished() {
        registry.remove(request_id);
    }

    let callback = Py::new(
        py,
        PythonFutureCancellation::new(request_id, registry.clone()),
    )?;
    if let Err(err) = future
        .bind(py)
        .call_method1("add_done_callback", (callback,))
        .map(|_| ())
    {
        registry.abort_request(request_id);
        return Err(err);
    }

    Ok(future)
}
