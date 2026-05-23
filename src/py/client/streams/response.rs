use super::callback::PythonStreamReadCancellation;
use super::parts::RawStreamResponseParts;
use super::state::{ActiveStreamRead, StreamState, StreamStateParts};
use crate::core::headers::HeaderPairs;
use crate::py::client::future::complete_python_bytes_future;
use crate::py::response::{RawRequestInfo, RawResponse};
use pyo3::prelude::*;
use pyo3::types::PyAny;
use tokio::runtime::Handle;
use tokio::sync::oneshot;

#[pyclass(skip_from_py_object)]
pub struct RawStreamResponse {
    #[pyo3(get)]
    status_code: u16,
    #[pyo3(get)]
    headers: HeaderPairs,
    #[pyo3(get)]
    url: String,
    #[pyo3(get)]
    request: RawRequestInfo,
    #[pyo3(get)]
    http_version: String,
    #[pyo3(get)]
    elapsed: f64,
    history: Vec<RawResponse>,
    state: StreamState,
    runtime_handle: Handle,
}

impl RawStreamResponse {
    pub(crate) fn from_parts(parts: RawStreamResponseParts) -> Self {
        let RawStreamResponseParts {
            status_code,
            headers,
            url,
            request,
            http_version,
            elapsed,
            history,
            body,
            permit,
            lifecycle,
            connection_use,
            successful_body_outcome,
            metrics,
            completion,
            registry,
            runtime_handle,
            read_timeout,
            read_timeout_secs,
            origin,
            redirect_hop,
        } = parts;
        Self {
            status_code,
            headers,
            url,
            request,
            http_version,
            elapsed,
            history,
            state: StreamState::new(StreamStateParts {
                body,
                permit,
                lifecycle,
                connection_use,
                successful_body_outcome,
                metrics,
                completion,
                registry,
                read_timeout,
                read_timeout_secs,
                origin,
                redirect_hop,
            }),
            runtime_handle,
        }
    }

    fn release_body_reservations(&mut self) {
        for response in &mut self.history {
            response.release_body_reservations();
        }
    }
}

#[pymethods]
impl RawStreamResponse {
    #[getter]
    fn history(&self) -> Vec<RawResponse> {
        self.history.clone()
    }

    fn close(&self) {
        self.state.abort();
    }

    fn next_chunk_async(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let loop_ = py
            .import("asyncio")?
            .call_method0("get_running_loop")?
            .unbind();
        let future = loop_.bind(py).call_method0("create_future")?.unbind();
        let state = self.state.clone();
        let Some(read_guard) = state.start_read()? else {
            future.bind(py).call_method1("set_result", (py.None(),))?;
            return Ok(future);
        };
        let task_loop = loop_.clone_ref(py);
        let task_future = future.clone_ref(py);
        let (start_sender, start_receiver) = oneshot::channel();

        let handle = self.runtime_handle.spawn(async move {
            if start_receiver.await.is_err() {
                return;
            }
            let result = read_guard.read_next_chunk().await;
            complete_python_bytes_future(&task_loop, &task_future, result);
        });
        let abort_handle = handle.abort_handle();
        if !state.register_read_task(ActiveStreamRead::new(
            abort_handle.clone(),
            loop_.clone_ref(py),
            future.clone_ref(py),
        )) {
            handle.abort();
            future.bind(py).call_method1("set_result", (py.None(),))?;
            return Ok(future);
        }

        let callback = Py::new(
            py,
            PythonStreamReadCancellation::new(state.clone(), abort_handle),
        )?;
        if let Err(err) = future
            .bind(py)
            .call_method1("add_done_callback", (callback,))
            .map(|_| ())
        {
            state.abort();
            return Err(err);
        }
        if start_sender.send(()).is_err() {
            state.abort();
        }

        Ok(future)
    }

    fn release_buffered_body_reservations(&mut self) {
        self.release_body_reservations();
    }
}

impl Drop for RawStreamResponse {
    fn drop(&mut self) {
        self.state.abort();
    }
}
