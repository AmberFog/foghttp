use super::current_request_write_timeout;
use bytes::Bytes;
use http_body_util::{combinators::UnsyncBoxBody, BodyExt, Full};
use hyper::body::{Frame, SizeHint};
use std::collections::VecDeque;
use std::convert::Infallible;
use std::future::Future;
use std::io;
use std::pin::Pin;
use std::sync::{Arc, Condvar, Mutex, MutexGuard};
use std::task::{Context, Poll};
use std::time::Instant;
use tokio::time::Sleep;

pub(crate) type BodyError = Box<dyn std::error::Error + Send + Sync>;
pub(crate) type RequestBody = UnsyncBoxBody<Bytes, BodyError>;
pub(crate) type UploadBodyItem = Result<Bytes, String>;

#[derive(Clone)]
pub(crate) struct UploadBodySender {
    channel: Arc<UploadBodyChannel>,
}

pub(crate) struct UploadBodyReceiver {
    channel: Arc<UploadBodyChannel>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum UploadBodySendError {
    Full,
    Closed,
}

pub(crate) type ReadyCallback = Arc<dyn Fn() + Send + Sync>;

struct UploadBodyChannel {
    state: Mutex<UploadBodyChannelState>,
    send_ready: Condvar,
    capacity: usize,
}

struct UploadBodyChannelState {
    queue: VecDeque<UploadBodyItem>,
    closed: bool,
    ready_callback: Option<ReadyCallback>,
    receive_waker: Option<std::task::Waker>,
}

pub(crate) fn upload_body_channel(capacity: usize) -> (UploadBodySender, UploadBodyReceiver) {
    assert!(
        capacity > 0,
        "upload body channel capacity must be greater than 0"
    );
    let channel = Arc::new(UploadBodyChannel {
        state: Mutex::new(UploadBodyChannelState {
            queue: VecDeque::with_capacity(capacity),
            closed: false,
            ready_callback: None,
            receive_waker: None,
        }),
        send_ready: Condvar::new(),
        capacity,
    });
    (
        UploadBodySender {
            channel: Arc::clone(&channel),
        },
        UploadBodyReceiver { channel },
    )
}

pub(crate) fn buffered_request_body(content: Option<Vec<u8>>) -> RequestBody {
    Full::new(Bytes::from(content.unwrap_or_default()))
        .map_err(infallible_body_error)
        .boxed_unsync()
}

pub(crate) fn streaming_request_body(
    receiver: UploadBodyReceiver,
    content_length: Option<u64>,
) -> RequestBody {
    UnsyncBoxBody::new(StreamingUploadBody::new(receiver, content_length))
}

fn infallible_body_error(error: Infallible) -> BodyError {
    match error {}
}

struct StreamingUploadBody {
    receiver: UploadBodyReceiver,
    content_length: Option<u64>,
    pending_timeout: Option<Pin<Box<Sleep>>>,
    pending_timeout_started: Option<Instant>,
    finished: bool,
}

impl StreamingUploadBody {
    fn new(receiver: UploadBodyReceiver, content_length: Option<u64>) -> Self {
        Self {
            receiver,
            content_length,
            pending_timeout: None,
            pending_timeout_started: None,
            finished: false,
        }
    }

    fn clear_pending_timeout(&mut self) {
        self.pending_timeout = None;
        self.pending_timeout_started = None;
    }

    fn poll_pending_timeout(&mut self, context: &mut Context<'_>) -> Poll<Option<BodyError>> {
        let Some(write_timeout) = current_request_write_timeout() else {
            return Poll::Pending;
        };
        let started = *self
            .pending_timeout_started
            .get_or_insert_with(Instant::now);
        let timeout = self
            .pending_timeout
            .get_or_insert_with(|| Box::pin(tokio::time::sleep(write_timeout.timeout())));
        if timeout.as_mut().poll(context).is_pending() {
            return Poll::Pending;
        }
        self.finished = true;
        Poll::Ready(Some(Box::new(write_timeout.timeout_error(started))))
    }
}

impl hyper::body::Body for StreamingUploadBody {
    type Data = Bytes;
    type Error = BodyError;

    fn poll_frame(
        mut self: Pin<&mut Self>,
        context: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Self::Data>, Self::Error>>> {
        if self.finished {
            return Poll::Ready(None);
        }

        match self.receiver.poll_recv(context) {
            Poll::Ready(Some(Ok(chunk))) => {
                self.clear_pending_timeout();
                Poll::Ready(Some(Ok(Frame::data(chunk))))
            }
            Poll::Ready(Some(Err(message))) => {
                self.clear_pending_timeout();
                self.finished = true;
                Poll::Ready(Some(Err(Box::new(io::Error::other(message)))))
            }
            Poll::Ready(None) => {
                self.clear_pending_timeout();
                self.finished = true;
                Poll::Ready(None)
            }
            Poll::Pending => match self.poll_pending_timeout(context) {
                Poll::Ready(Some(error)) => Poll::Ready(Some(Err(error))),
                Poll::Ready(None) | Poll::Pending => Poll::Pending,
            },
        }
    }

    fn is_end_stream(&self) -> bool {
        self.finished
    }

    fn size_hint(&self) -> SizeHint {
        let mut hint = SizeHint::new();
        if let Some(content_length) = self.content_length {
            hint.set_exact(content_length);
        }
        hint
    }
}

impl UploadBodySender {
    pub(crate) fn send_blocking(&self, item: UploadBodyItem) -> bool {
        let mut state = self.channel.state();
        loop {
            if state.closed {
                return false;
            }
            if state.queue.len() < self.channel.capacity {
                state.queue.push_back(item);
                let waker = state.receive_waker.take();
                drop(state);
                if let Some(waker) = waker {
                    waker.wake();
                }
                return true;
            }
            state = self.channel.wait_send_ready(state);
        }
    }

    pub(crate) fn send_nowait(&self, item: UploadBodyItem) -> Result<(), UploadBodySendError> {
        let mut state = self.channel.state();
        if state.closed {
            return Err(UploadBodySendError::Closed);
        }
        if state.queue.len() >= self.channel.capacity {
            return Err(UploadBodySendError::Full);
        }
        state.queue.push_back(item);
        let waker = state.receive_waker.take();
        drop(state);
        if let Some(waker) = waker {
            waker.wake();
        }
        Ok(())
    }

    pub(crate) fn close(&self) {
        self.channel.abort();
    }

    pub(crate) fn finish(&self) {
        self.channel.finish();
    }

    pub(crate) fn is_closed(&self) -> bool {
        self.channel.state().closed
    }

    pub(crate) fn set_ready_callback(&self, callback: Option<ReadyCallback>) {
        self.channel.state().ready_callback = callback;
    }
}

impl UploadBodyReceiver {
    fn poll_recv(&mut self, context: &mut Context<'_>) -> Poll<Option<UploadBodyItem>> {
        let mut state = self.channel.state();
        if let Some(item) = state.queue.pop_front() {
            let callback = state.ready_callback.clone();
            drop(state);
            self.channel.notify_sender(callback);
            return Poll::Ready(Some(item));
        }
        if state.closed {
            return Poll::Ready(None);
        }
        state.receive_waker = Some(context.waker().clone());
        Poll::Pending
    }
}

impl Drop for UploadBodyReceiver {
    fn drop(&mut self) {
        self.channel.abort();
    }
}

impl UploadBodyChannel {
    fn state(&self) -> MutexGuard<'_, UploadBodyChannelState> {
        self.state
            .lock()
            .expect("upload body channel lock poisoned")
    }

    fn wait_send_ready<'a>(
        &self,
        state: MutexGuard<'a, UploadBodyChannelState>,
    ) -> MutexGuard<'a, UploadBodyChannelState> {
        self.send_ready
            .wait(state)
            .expect("upload body channel lock poisoned")
    }

    fn notify_sender(&self, callback: Option<ReadyCallback>) {
        self.send_ready.notify_one();
        if let Some(callback) = callback {
            callback();
        }
    }

    fn abort(&self) {
        let mut state = self.state();
        if state.closed {
            return;
        }
        state.closed = true;
        state.queue.clear();
        let waker = state.receive_waker.take();
        let callback = state.ready_callback.clone();
        drop(state);
        self.send_ready.notify_all();
        if let Some(waker) = waker {
            waker.wake();
        }
        if let Some(callback) = callback {
            callback();
        }
    }

    fn finish(&self) {
        let mut state = self.state();
        if state.closed {
            return;
        }
        state.closed = true;
        let waker = state.receive_waker.take();
        let callback = state.ready_callback.clone();
        drop(state);
        self.send_ready.notify_all();
        if let Some(waker) = waker {
            waker.wake();
        }
        if let Some(callback) = callback {
            callback();
        }
    }
}
