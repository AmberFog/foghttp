use super::RawClient;
use crate::core::client::{
    upload_body_channel_with_budget, UploadBodyAccount, UploadBodyBudget, UploadBodyReceiver,
    UploadBodySendError, UploadBodySender, DEFAULT_MAX_BUFFERED_UPLOAD_BYTES,
    DEFAULT_MAX_UPLOAD_BUFFER_BYTES,
};
use pyo3::prelude::*;
use pyo3::types::PyAny;
use std::sync::{Arc, Mutex};

mod startup;
use startup::UploadStartupGuard;

const UPLOAD_BODY_CHANNEL_CAPACITY: usize = 8;
const STREAMING_BODY_CONSUMED: &str = "streaming request body was already consumed";

#[pyclass(module = "foghttp._foghttp", skip_from_py_object)]
#[derive(Clone)]
pub struct RawUploadBody {
    inner: RawUploadBodyInner,
    account: Arc<UploadBodyAccount>,
}

#[derive(Clone)]
enum RawUploadBodyInner {
    Owner(Arc<Mutex<RawUploadBodyState>>),
    Attempt(UploadBodySender),
}

struct RawUploadBodyState {
    sender: Option<UploadBodySender>,
    receiver: Option<UploadBodyReceiver>,
    content_length: Option<u64>,
    start_callback: Arc<Py<PyAny>>,
    replayable: bool,
    ready_callback: Option<Arc<dyn Fn() + Send + Sync>>,
}

#[pymethods]
impl RawUploadBody {
    #[new]
    #[pyo3(signature = (content_length, start_callback, replayable, ready_callback, *, raw_client=None))]
    fn new(
        content_length: Option<u64>,
        start_callback: Py<PyAny>,
        replayable: bool,
        ready_callback: Option<Py<PyAny>>,
        raw_client: Option<PyRef<'_, RawClient>>,
    ) -> PyResult<Self> {
        let (budget, max_upload_buffer_bytes) = if let Some(client) = raw_client {
            client.ensure_current_process()?;
            client.clients_unchecked()?;
            (
                Arc::clone(&client.upload_body_budget),
                client.max_upload_buffer_bytes,
            )
        } else {
            (
                Arc::new(UploadBodyBudget::new(DEFAULT_MAX_BUFFERED_UPLOAD_BYTES)),
                DEFAULT_MAX_UPLOAD_BUFFER_BYTES,
            )
        };
        let account = Arc::new(UploadBodyAccount::new(max_upload_buffer_bytes, budget));
        let ready_callback = ready_callback.map(ready_callback_wrapper);
        let (sender, receiver) = new_upload_body_channel(ready_callback.as_ref(), &account);
        Ok(Self {
            inner: RawUploadBodyInner::Owner(Arc::new(Mutex::new(RawUploadBodyState {
                sender: Some(sender),
                receiver: Some(receiver),
                content_length,
                start_callback: Arc::new(start_callback),
                replayable,
                ready_callback,
            }))),
            account,
        })
    }

    fn send(&self, py: Python<'_>, chunk: &[u8]) -> PyResult<bool> {
        self.send_blocking(py, chunk, false)
    }

    fn send_final(&self, py: Python<'_>, chunk: &[u8]) -> PyResult<bool> {
        self.send_blocking(py, chunk, true)
    }

    fn send_nowait(&self, chunk: &[u8]) -> bool {
        self.send_fragment_nowait(chunk, false)
    }

    fn send_final_nowait(&self, chunk: &[u8]) -> bool {
        self.send_fragment_nowait(chunk, true)
    }

    #[pyo3(signature = (chunk, offset, *, r#final=false))]
    fn send_part_nowait(&self, chunk: &[u8], offset: usize, r#final: bool) -> PyResult<usize> {
        if offset > chunk.len() {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "upload chunk offset exceeds its byte length",
            ));
        }
        let Some(sender) = self.sender() else {
            return Ok(0);
        };
        let length = sender.max_chunk_size().min(chunk.len() - offset);
        if length == 0 {
            return Ok(0);
        }
        let end = offset + length;
        let final_chunk = r#final && end == chunk.len();
        Ok(
            if sender
                .send_slice_nowait(&chunk[offset..end], final_chunk)
                .is_ok()
            {
                length
            } else {
                0
            },
        )
    }

    fn is_closed(&self) -> bool {
        match self.sender() {
            Some(sender) => sender.is_closed(),
            None => true,
        }
    }

    fn finish(&self) {
        if let Some(sender) = self.sender() {
            sender.finish();
        }
    }

    fn fail(&self, py: Python<'_>, message: String) -> PyResult<()> {
        let Some(sender) = self.sender() else {
            return Ok(());
        };
        if startup::is_active(&sender) {
            match sender.send_nowait(Err(message)) {
                Ok(()) => {}
                Err(UploadBodySendError::Closed) => return Ok(()),
                Err(UploadBodySendError::Full) => return Err(startup::reject(&sender)),
            }
        } else {
            let _sent = py.detach(|| sender.send_blocking(Err(message)));
        }
        sender.finish();
        Ok(())
    }

    fn fail_nowait(&self, message: String) -> bool {
        let Some(sender) = self.sender() else {
            return true;
        };
        match sender.send_nowait(Err(message)) {
            Ok(()) => {
                sender.finish();
                true
            }
            Err(UploadBodySendError::Full) => false,
            Err(UploadBodySendError::Closed) => true,
        }
    }

    fn close(&self) {
        if let Some(sender) = self.take_sender() {
            sender.close();
        }
    }
}

impl RawUploadBody {
    pub(super) fn ensure_budget(&self, budget: &Arc<UploadBodyBudget>) -> PyResult<()> {
        if self.account.belongs_to(budget) {
            return Ok(());
        }
        Err(pyo3::exceptions::PyValueError::new_err(
            "upload body must be constructed with its receiving raw_client",
        ))
    }

    fn send_blocking(&self, py: Python<'_>, chunk: &[u8], final_chunk: bool) -> PyResult<bool> {
        if chunk.is_empty() {
            return Ok(self.send_fragment_nowait(chunk, final_chunk));
        }
        let Some(sender) = self.sender() else {
            return Ok(false);
        };
        if startup::is_active(&sender) {
            return startup::send_fragments(&sender, chunk, final_chunk);
        }
        Ok(py.detach(|| {
            let fragments = chunk.chunks(sender.max_chunk_size());
            let last_index = fragments.len() - 1;
            for (index, fragment) in fragments.enumerate() {
                if !sender.send_slice_blocking(fragment, final_chunk && index == last_index) {
                    return false;
                }
            }
            true
        }))
    }

    fn send_fragment_nowait(&self, chunk: &[u8], final_chunk: bool) -> bool {
        if chunk.is_empty() {
            return if final_chunk {
                self.sender().is_some_and(|sender| sender.finish())
            } else {
                self.sender().is_some_and(|sender| !sender.is_closed())
            };
        }
        let Some(sender) = self.sender() else {
            return false;
        };
        sender.send_slice_nowait(chunk, final_chunk).is_ok()
    }
    pub(crate) fn take_receiver(
        &self,
        py: Python<'_>,
    ) -> PyResult<(UploadBodyReceiver, Option<u64>)> {
        let RawUploadBodyInner::Owner(state) = &self.inner else {
            return Err(pyo3::exceptions::PyRuntimeError::new_err(
                STREAMING_BODY_CONSUMED,
            ));
        };
        let (receiver, content_length, start_callback, attempt_sender, previous_sender) = {
            let mut state = state.lock().expect("raw upload body lock poisoned");
            let previous_sender = if state.receiver.is_none() {
                if !state.replayable {
                    return Err(pyo3::exceptions::PyRuntimeError::new_err(
                        STREAMING_BODY_CONSUMED,
                    ));
                }
                state.reset_channel(&self.account)
            } else {
                None
            };
            let Some(receiver) = state.receiver.take() else {
                return Err(pyo3::exceptions::PyRuntimeError::new_err(
                    STREAMING_BODY_CONSUMED,
                ));
            };
            let Some(attempt_sender) = state.sender.clone() else {
                return Err(pyo3::exceptions::PyRuntimeError::new_err(
                    STREAMING_BODY_CONSUMED,
                ));
            };
            (
                receiver,
                state.content_length,
                Arc::clone(&state.start_callback),
                attempt_sender,
                previous_sender,
            )
        };
        if let Some(sender) = previous_sender {
            sender.close();
        }

        let attempt_body = Py::new(
            py,
            Self {
                inner: RawUploadBodyInner::Attempt(attempt_sender.clone()),
                account: Arc::clone(&self.account),
            },
        )?;
        let startup = UploadStartupGuard::enter(&attempt_sender);
        let callback_result = start_callback.bind(py).call1((attempt_body,)).map(|_| ());
        if let Err(error) = startup.complete(callback_result) {
            attempt_sender.close();
            return Err(error);
        }
        Ok((receiver, content_length))
    }

    fn sender(&self) -> Option<UploadBodySender> {
        match &self.inner {
            RawUploadBodyInner::Owner(state) => state
                .lock()
                .expect("raw upload body lock poisoned")
                .sender
                .clone(),
            RawUploadBodyInner::Attempt(sender) => Some(sender.clone()),
        }
    }

    fn take_sender(&self) -> Option<UploadBodySender> {
        match &self.inner {
            RawUploadBodyInner::Owner(state) => state
                .lock()
                .expect("raw upload body lock poisoned")
                .sender
                .take(),
            RawUploadBodyInner::Attempt(sender) => Some(sender.clone()),
        }
    }
}

impl RawUploadBodyState {
    fn reset_channel(&mut self, account: &Arc<UploadBodyAccount>) -> Option<UploadBodySender> {
        let previous_sender = self.sender.take();
        let (sender, receiver) = new_upload_body_channel(self.ready_callback.as_ref(), account);
        self.sender = Some(sender);
        self.receiver = Some(receiver);
        previous_sender
    }
}

fn new_upload_body_channel(
    ready_callback: Option<&Arc<dyn Fn() + Send + Sync>>,
    account: &Arc<UploadBodyAccount>,
) -> (UploadBodySender, UploadBodyReceiver) {
    let (sender, receiver) =
        upload_body_channel_with_budget(UPLOAD_BODY_CHANNEL_CAPACITY, Arc::clone(account));
    if let Some(callback) = ready_callback {
        sender.set_ready_callback(Some(Arc::clone(callback)));
    }
    (sender, receiver)
}

fn ready_callback_wrapper(callback: Py<PyAny>) -> Arc<dyn Fn() + Send + Sync> {
    Arc::new(move || {
        Python::attach(|py| {
            if let Err(error) = callback.bind(py).call0() {
                error.write_unraisable(py, Some(callback.bind(py)));
            }
        });
    })
}

#[cfg(test)]
mod tests;

#[cfg(test)]
mod budget_lifecycle_tests;
