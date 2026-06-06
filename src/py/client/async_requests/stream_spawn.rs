use super::active::{ActiveAsyncRequest, RequestCompletion};
use super::callback::PythonFutureCancellation;
use super::registry::AsyncRequestRegistry;
use crate::core::metrics::Metrics;
use crate::errors::FogHttpError;
use crate::messages::STREAM_REQUEST_TASK_START_FAILED;
use crate::py::client::acquire::AcquireGate;
use crate::py::client::future::complete_python_stream_future;
use crate::py::client::streams::StreamRegistry;
use crate::py::client::transport::{send_stream_request, TransportClients, TransportRequest};
use pyo3::prelude::*;
use pyo3::types::PyAny;
use std::sync::Arc;
use tokio::runtime::Runtime;
use tokio::sync::oneshot;

pub struct AsyncStreamRequestSpawn {
    pub acquire_gate: AcquireGate,
    pub clients: TransportClients,
    pub metrics: Arc<Metrics>,
    pub active_streams: StreamRegistry,
    pub pool_timeout: f64,
    pub request: TransportRequest,
}

pub fn spawn_async_stream_request(
    py: Python<'_>,
    runtime: &Runtime,
    registry: &AsyncRequestRegistry,
    spawn: AsyncStreamRequestSpawn,
) -> PyResult<Py<PyAny>> {
    let AsyncStreamRequestSpawn {
        acquire_gate,
        clients,
        metrics,
        active_streams,
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
    let runtime_handle = runtime.handle().clone();

    let task_loop = loop_.clone_ref(py);
    let task_future = future.clone_ref(py);
    let task_registry = registry.clone();
    let task_metrics = Arc::clone(&metrics);
    let task_completion = completion.clone();
    let (start_sender, start_receiver) = oneshot::channel();

    metrics.request_started();
    let handle = runtime.spawn(async move {
        if start_receiver.await.is_err() {
            return;
        }
        let result = send_stream_request(
            clients,
            acquire_gate,
            Arc::clone(&task_metrics),
            active_streams,
            runtime_handle,
            pool_timeout,
            request,
            task_completion.clone(),
        )
        .await;
        task_registry.remove(request_id);
        if result.is_err() && task_completion.finish() {
            task_metrics.request_finished(true);
        }
        complete_python_stream_future(&task_loop, &task_future, result);
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
    if start_sender.send(()).is_err() {
        registry.abort_request(request_id);
        return Err(FogHttpError::new_err(STREAM_REQUEST_TASK_START_FAILED));
    }

    Ok(future)
}
