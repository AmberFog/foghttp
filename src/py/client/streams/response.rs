use super::callback::PythonStreamReadCallback;
use super::parts::RawStreamResponseParts;
use super::state::{ActiveStreamRead, ReadyFrameCoalescing, StreamState, StreamStateParts};
use crate::core::headers::HeaderPairs;
use crate::errors::FogHttpError;
use crate::messages::STREAM_RESPONSE_READ_ABORTED;
use crate::py::client::future::{complete_python_bytes_future, PythonFutureSetters};
use crate::py::client::process::{current_process_id, stream_response_used_after_fork, ProcessId};
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
    state: Option<StreamState>,
    runtime_handle: Option<Handle>,
    future_setters: PythonFutureSetters,
    process_id: ProcessId,
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
            future_setters,
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
            state: Some(StreamState::new(StreamStateParts {
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
            })),
            runtime_handle: Some(runtime_handle),
            future_setters,
            process_id: current_process_id(),
        }
    }

    fn release_body_reservations(&mut self) {
        for response in &mut self.history {
            response.release_body_reservations();
        }
    }

    fn ensure_current_process(&self) -> PyResult<()> {
        let current_process_id = current_process_id();
        if self.process_id == current_process_id {
            return Ok(());
        }
        Err(stream_response_used_after_fork(
            self.process_id,
            current_process_id,
        ))
    }

    fn close_resources(&mut self) {
        let state = self.state.take();
        let runtime_handle = self.runtime_handle.take();
        if self.process_id == current_process_id() {
            if let Some(state) = state {
                state.abort();
            }
            drop(runtime_handle);
        } else {
            // Aborting inherited stream state may lock or schedule on parent threads.
            std::mem::forget(state);
            std::mem::forget(runtime_handle);
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
        if self.process_id != current_process_id() {
            return;
        }
        if let Some(state) = &self.state {
            state.abort();
        }
    }

    fn next_chunk(&self, py: Python<'_>) -> PyResult<Option<Vec<u8>>> {
        self.ensure_current_process()?;
        let Some(state) = self.state.clone() else {
            return Ok(None);
        };
        let runtime_handle = self
            .runtime_handle
            .as_ref()
            .ok_or_else(|| FogHttpError::new_err(STREAM_RESPONSE_READ_ABORTED))?;
        let Some(read_guard) = state.start_read(ReadyFrameCoalescing::Disabled)? else {
            return Ok(None);
        };
        let (result_sender, result_receiver) = oneshot::channel();
        let (start_sender, start_receiver) = oneshot::channel();
        let handle = runtime_handle.spawn(async move {
            if start_receiver.await.is_err() {
                return;
            }
            let _ = result_sender.send(read_guard.read_next_chunk().await);
        });
        let abort_handle = handle.abort_handle();
        if !state.register_read_task(ActiveStreamRead::new_sync(abort_handle)) {
            return Err(FogHttpError::new_err(STREAM_RESPONSE_READ_ABORTED));
        }
        if start_sender.send(()).is_err() {
            state.abort();
            return Err(FogHttpError::new_err(STREAM_RESPONSE_READ_ABORTED));
        }

        let result = py.detach(|| runtime_handle.block_on(result_receiver));
        state.finish_read_delivery();
        result.map_err(|_| FogHttpError::new_err(STREAM_RESPONSE_READ_ABORTED))?
    }

    fn next_chunk_async(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.ensure_current_process()?;
        let loop_ = py
            .import("asyncio")?
            .call_method0("get_running_loop")?
            .unbind();
        let future = loop_.bind(py).call_method0("create_future")?.unbind();
        let Some(state) = self.state.clone() else {
            future.bind(py).call_method1("set_result", (py.None(),))?;
            return Ok(future);
        };
        let runtime_handle = self
            .runtime_handle
            .as_ref()
            .ok_or_else(|| FogHttpError::new_err(STREAM_RESPONSE_READ_ABORTED))?;
        let Some(read_guard) = state.start_read(ReadyFrameCoalescing::Enabled)? else {
            future.bind(py).call_method1("set_result", (py.None(),))?;
            return Ok(future);
        };
        let task_loop = loop_.clone_ref(py);
        let task_future = future.clone_ref(py);
        let task_future_setters = self.future_setters.clone_ref(py);
        let (start_sender, start_receiver) = oneshot::channel();

        let handle = runtime_handle.spawn(async move {
            if start_receiver.await.is_err() {
                return;
            }
            let result = read_guard.read_next_chunk().await;
            complete_python_bytes_future(&task_loop, &task_future, &task_future_setters, result);
        });
        let abort_handle = handle.abort_handle();
        if !state.register_read_task(ActiveStreamRead::new_async(
            abort_handle.clone(),
            loop_.clone_ref(py),
            future.clone_ref(py),
        )) {
            return Ok(future);
        }

        let callback = Py::new(
            py,
            PythonStreamReadCallback::new(state.clone(), abort_handle),
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

    fn release_buffered_body_reservations(&mut self) -> PyResult<()> {
        self.ensure_current_process()?;
        self.release_body_reservations();
        Ok(())
    }
}

impl Drop for RawStreamResponse {
    fn drop(&mut self) {
        self.close_resources();
    }
}
