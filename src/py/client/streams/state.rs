use super::constants::{MAX_READY_FRAME_COALESCE_COUNT, READY_FRAME_COALESCE_TARGET_BYTES};
use super::read::next_stream_body_frame;
use super::registry::StreamRegistry;
use crate::core::client::ConnectionUseGuard;
use crate::core::metrics::{Metrics, ResponseBodyLifecycleOutcome};
use crate::errors::FogHttpError;
use crate::py::client::acquire::AcquirePermit;
use crate::py::client::async_requests::RequestCompletion;
use crate::py::client::future::cancel_python_future;
use crate::py::client::lifecycle::ResponseBodyLifecycle;
use bytes::Bytes;
use hyper::body::Body;
use hyper::body::Incoming;
use pyo3::prelude::*;
use pyo3::types::PyAny;
use std::pin::Pin;
use std::sync::{Arc, Mutex, MutexGuard};
use std::task::{Context, Poll, Waker};
use std::time::Duration;
use tokio::task::AbortHandle;

pub(super) struct StreamStateParts {
    pub(super) body: Incoming,
    pub(super) permit: AcquirePermit,
    pub(super) lifecycle: ResponseBodyLifecycle,
    pub(super) connection_use: Option<ConnectionUseGuard>,
    pub(super) successful_body_outcome: ResponseBodyLifecycleOutcome,
    pub(super) metrics: Arc<Metrics>,
    pub(super) completion: RequestCompletion,
    pub(super) registry: StreamRegistry,
    pub(super) read_timeout: Duration,
    pub(super) read_timeout_secs: f64,
    pub(super) origin: String,
    pub(super) redirect_hop: usize,
}

#[derive(Clone)]
pub(super) struct StreamState {
    pub(super) inner: Arc<StreamStateInner>,
}

pub(super) struct StreamStateInner {
    stream_id: u64,
    registry: StreamRegistry,
    fields: Mutex<StreamStateFields>,
}

struct StreamStateFields {
    body: Option<Incoming>,
    permit: Option<AcquirePermit>,
    lifecycle: Option<ResponseBodyLifecycle>,
    connection_use: Option<ConnectionUseGuard>,
    read_task: Option<ActiveStreamRead>,
    read_in_progress: bool,
    finished: bool,
    successful_body_outcome: ResponseBodyLifecycleOutcome,
    metrics: Arc<Metrics>,
    completion: RequestCompletion,
    read_timeout: Duration,
    read_timeout_secs: f64,
    origin: String,
    redirect_hop: usize,
}

pub(super) struct StreamReadGuard {
    state: StreamState,
    body: Option<Incoming>,
    read_timeout: Duration,
    read_timeout_secs: f64,
    origin: String,
    redirect_hop: usize,
    coalesce_ready_frames: bool,
    disarmed: bool,
}

pub(super) struct ActiveStreamRead {
    abort_handle: AbortHandle,
    notification: StreamReadNotification,
}

enum ReadyBodyFrame {
    Data(Bytes),
    Eof,
    Pending,
}

enum StreamReadNotification {
    Async { loop_: Py<PyAny>, future: Py<PyAny> },
    Sync,
}

impl StreamState {
    pub(super) fn new(parts: StreamStateParts) -> Self {
        let stream_id = parts.registry.next_stream_id();
        let registry = parts.registry.clone();
        let inner = Arc::new(StreamStateInner {
            stream_id,
            registry,
            fields: Mutex::new(StreamStateFields {
                body: Some(parts.body),
                permit: Some(parts.permit),
                lifecycle: Some(parts.lifecycle),
                connection_use: parts.connection_use,
                read_task: None,
                read_in_progress: false,
                finished: false,
                successful_body_outcome: parts.successful_body_outcome,
                metrics: parts.metrics,
                completion: parts.completion,
                read_timeout: parts.read_timeout,
                read_timeout_secs: parts.read_timeout_secs,
                origin: parts.origin,
                redirect_hop: parts.redirect_hop,
            }),
        });
        parts.registry.insert(stream_id, &inner);
        Self { inner }
    }

    pub(super) fn start_read(
        &self,
        coalesce_ready_frames: bool,
    ) -> PyResult<Option<StreamReadGuard>> {
        let mut fields = self.fields();
        if fields.finished {
            return Ok(None);
        }
        if fields.read_in_progress {
            return Err(FogHttpError::new_err(
                "stream response body read is already in progress",
            ));
        }

        let Some(body) = fields.body.take() else {
            return Ok(None);
        };
        fields.read_in_progress = true;

        Ok(Some(StreamReadGuard {
            state: self.clone(),
            body: Some(body),
            read_timeout: fields.read_timeout,
            read_timeout_secs: fields.read_timeout_secs,
            origin: fields.origin.clone(),
            redirect_hop: fields.redirect_hop,
            coalesce_ready_frames,
            disarmed: false,
        }))
    }

    pub(super) fn register_read_task(&self, read_task: ActiveStreamRead) -> bool {
        let mut fields = self.fields();
        if fields.finished || !fields.read_in_progress {
            drop(fields);
            read_task.abort_and_notify();
            return false;
        }
        fields.read_task = Some(read_task);
        true
    }

    pub(super) fn is_finished(&self) -> bool {
        self.fields().finished
    }

    pub(super) fn abort(&self) {
        self.finish(StreamFinish::Abort, true);
    }

    pub(super) fn finish_read_delivery(&self) {
        let mut fields = self.fields();
        if fields.finished {
            return;
        }
        fields.read_task = None;
        fields.read_in_progress = false;
    }

    fn complete_read(&self, body: Incoming) {
        let mut fields = self.fields();
        if fields.finished {
            return;
        }
        fields.body = Some(body);
    }

    fn finish_success_from_read(&self) {
        self.finish(StreamFinish::Success, false);
    }

    fn abort_from_read(&self) {
        self.finish(StreamFinish::Abort, false);
    }

    fn finish(&self, finish: StreamFinish, abort_read_task: bool) {
        let (finished_request, metrics, read_task_to_cancel) = {
            let mut fields = self.fields();
            if fields.finished {
                return;
            }
            fields.finished = true;
            self.inner.registry.remove(self.inner.stream_id);
            let read_task_to_cancel = if abort_read_task {
                fields.read_task.take()
            } else {
                fields.read_task.take();
                None
            };
            fields.body.take();
            match finish {
                StreamFinish::Success => fields.finish_successful_body(),
                StreamFinish::Abort => fields.finish_aborted_body(),
            }
            fields.permit.take();
            let metrics = Arc::clone(&fields.metrics);
            let finished_request = fields.completion.finish();
            (finished_request, metrics, read_task_to_cancel)
        };

        if let Some(read_task) = read_task_to_cancel {
            read_task.abort_and_notify();
        }

        if finished_request {
            let failed = matches!(finish, StreamFinish::Abort);
            metrics.request_finished(failed);
        }
    }

    fn fields(&self) -> MutexGuard<'_, StreamStateFields> {
        self.inner
            .fields
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

impl ActiveStreamRead {
    pub(super) fn new_async(
        abort_handle: AbortHandle,
        loop_: Py<PyAny>,
        future: Py<PyAny>,
    ) -> Self {
        Self {
            abort_handle,
            notification: StreamReadNotification::Async { loop_, future },
        }
    }

    pub(super) fn new_sync(abort_handle: AbortHandle) -> Self {
        Self {
            abort_handle,
            notification: StreamReadNotification::Sync,
        }
    }

    fn abort_and_notify(self) {
        self.abort_handle.abort();
        if let StreamReadNotification::Async { loop_, future } = self.notification {
            cancel_python_future(&loop_, &future);
        }
    }
}

impl StreamStateFields {
    fn finish_successful_body(&mut self) {
        if let Some(connection_use) = self.connection_use.take() {
            connection_use.finish(self.successful_body_outcome);
        }
        if let Some(lifecycle) = &mut self.lifecycle {
            lifecycle.finish(self.successful_body_outcome);
        }
        self.lifecycle.take();
    }

    fn finish_aborted_body(&mut self) {
        if let Some(connection_use) = self.connection_use.take() {
            connection_use.finish(ResponseBodyLifecycleOutcome::Aborted);
        }
        if let Some(lifecycle) = &mut self.lifecycle {
            lifecycle.finish(ResponseBodyLifecycleOutcome::Aborted);
        }
        self.lifecycle.take();
    }
}

impl StreamReadGuard {
    pub(super) async fn read_next_chunk(mut self) -> PyResult<Option<Vec<u8>>> {
        loop {
            let read_timeout = self.read_timeout;
            let read_timeout_secs = self.read_timeout_secs;
            let origin = self.origin.clone();
            let redirect_hop = self.redirect_hop;
            let frame = next_stream_body_frame(
                self.body_mut(),
                read_timeout,
                read_timeout_secs,
                &origin,
                redirect_hop,
            )
            .await?;
            if self.state.is_finished() {
                return Ok(None);
            }
            let Some(frame) = frame else {
                self.finish_success_from_read();
                return Ok(None);
            };
            let frame = frame.map_err(|err| FogHttpError::new_err(err.to_string()))?;
            let Ok(data) = frame.into_data() else {
                continue;
            };

            let mut chunk = data.to_vec();
            let reached_eof =
                self.coalesce_ready_frames && self.drain_ready_data_frames(&mut chunk)?;
            if reached_eof {
                self.finish_success_from_read();
            } else {
                self.finish_chunk();
            }
            return Ok(Some(chunk));
        }
    }

    fn drain_ready_data_frames(&mut self, chunk: &mut Vec<u8>) -> PyResult<bool> {
        let mut coalesced_frames = 1;
        while chunk.len() < READY_FRAME_COALESCE_TARGET_BYTES
            && coalesced_frames < MAX_READY_FRAME_COALESCE_COUNT
        {
            match self.poll_ready_body_frame()? {
                ReadyBodyFrame::Data(data) => {
                    chunk.extend_from_slice(&data);
                    coalesced_frames += 1;
                }
                ReadyBodyFrame::Eof => return Ok(true),
                ReadyBodyFrame::Pending => return Ok(false),
            }
        }
        Ok(false)
    }

    fn poll_ready_body_frame(&mut self) -> PyResult<ReadyBodyFrame> {
        let waker = Waker::noop();
        let mut context = Context::from_waker(waker);
        loop {
            let frame = match Pin::new(self.body_mut()).poll_frame(&mut context) {
                Poll::Ready(frame) => frame,
                Poll::Pending => return Ok(ReadyBodyFrame::Pending),
            };
            let Some(frame) = frame else {
                return Ok(ReadyBodyFrame::Eof);
            };
            let frame = frame.map_err(|err| FogHttpError::new_err(err.to_string()))?;
            let Ok(data) = frame.into_data() else {
                continue;
            };
            return Ok(ReadyBodyFrame::Data(data));
        }
    }

    fn body_mut(&mut self) -> &mut Incoming {
        self.body
            .as_mut()
            .expect("stream read guard always owns a response body")
    }

    fn finish_chunk(mut self) {
        let body = self
            .body
            .take()
            .expect("stream read guard always owns a response body");
        self.state.complete_read(body);
        self.disarmed = true;
    }

    fn finish_success_from_read(mut self) {
        self.body.take();
        self.state.finish_success_from_read();
        self.disarmed = true;
    }
}

impl Drop for StreamReadGuard {
    fn drop(&mut self) {
        if !self.disarmed {
            self.body.take();
            self.state.abort_from_read();
        }
    }
}

#[derive(Clone, Copy)]
enum StreamFinish {
    Success,
    Abort,
}

#[cfg(test)]
#[path = "state_tests.rs"]
mod tests;
