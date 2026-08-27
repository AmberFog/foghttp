use super::{request_write_timeout_from_error, RequestWriteTimeout, RequestWriteTimeoutContext};
use bytes::Bytes;
use http_body_util::{combinators::UnsyncBoxBody, BodyExt, Full};
use hyper::body::{Frame, SizeHint};
use std::collections::VecDeque;
use std::convert::Infallible;
use std::future::Future;
use std::io;
use std::pin::Pin;
use std::sync::atomic::{AtomicU8, AtomicUsize, Ordering};
use std::sync::{Arc, Condvar, Mutex, MutexGuard};
use std::task::{Context, Poll};
use std::time::Instant;
use tokio::time::Sleep;

pub(crate) type BodyError = Box<dyn std::error::Error + Send + Sync>;
pub(crate) type RequestBody = UnsyncBoxBody<Bytes, BodyError>;
pub(crate) type UploadBodyItem = Result<Bytes, String>;

#[derive(Clone)]
pub(crate) struct RequestBodyCompletion {
    inner: Arc<RequestBodyCompletionInner>,
}

struct RequestBodyCompletionInner {
    expected_bytes: Option<u64>,
    producer_completion: Option<UploadBodyProducerCompletion>,
    state: Mutex<RequestBodyCompletionState>,
}

struct RequestBodyCompletionState {
    emitted_bytes: u64,
    reached_eof: bool,
    failed: bool,
    in_flight_frames: usize,
    transport_flushed: bool,
    write_timeout: Option<RequestWriteTimeout>,
}

struct TrackedBodyData {
    data: Bytes,
    completion: RequestBodyCompletion,
}

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
    producer_completion: UploadBodyProducerCompletion,
}

#[derive(Clone)]
struct UploadBodyProducerCompletion {
    inner: Arc<UploadBodyProducerCompletionInner>,
}

struct UploadBodyProducerCompletionInner {
    state: AtomicU8,
    outstanding_data_frames: AtomicUsize,
}

const PRODUCER_OPEN: u8 = 0;
const PRODUCER_FINISHED: u8 = 1;
const PRODUCER_FAILED: u8 = 2;
const PRODUCER_ABORTED: u8 = 3;

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
        producer_completion: UploadBodyProducerCompletion::new(),
    });
    (
        UploadBodySender {
            channel: Arc::clone(&channel),
        },
        UploadBodyReceiver { channel },
    )
}

pub(crate) fn buffered_request_body(
    content: Option<Vec<u8>>,
) -> (RequestBody, RequestBodyCompletion) {
    let content = content.unwrap_or_default();
    let content_length = u64::try_from(content.len()).expect("request body length fits u64");
    let body = Full::new(Bytes::from(content))
        .map_err(infallible_body_error)
        .boxed_unsync();
    tracked_request_body(body, Some(content_length), None)
}

pub(crate) fn streaming_request_body(
    receiver: UploadBodyReceiver,
    content_length: Option<u64>,
    write_timeout: Option<RequestWriteTimeoutContext>,
) -> (RequestBody, RequestBodyCompletion) {
    let producer_completion = receiver.producer_completion();
    let wire_content_length = content_length.filter(|length| *length > 0);
    let body = UnsyncBoxBody::new(StreamingUploadBody::new(
        receiver,
        wire_content_length,
        write_timeout,
    ));
    tracked_request_body(body, wire_content_length, Some(producer_completion))
}

fn tracked_request_body(
    body: RequestBody,
    expected_bytes: Option<u64>,
    producer_completion: Option<UploadBodyProducerCompletion>,
) -> (RequestBody, RequestBodyCompletion) {
    let completion = RequestBodyCompletion::new(expected_bytes, producer_completion);
    let tracked = TrackedRequestBody {
        body,
        completion: completion.clone(),
    };
    (tracked.boxed_unsync(), completion)
}

fn infallible_body_error(error: Infallible) -> BodyError {
    match error {}
}

struct TrackedRequestBody {
    body: RequestBody,
    completion: RequestBodyCompletion,
}

impl RequestBodyCompletion {
    fn new(
        expected_bytes: Option<u64>,
        producer_completion: Option<UploadBodyProducerCompletion>,
    ) -> Self {
        Self {
            inner: Arc::new(RequestBodyCompletionInner {
                expected_bytes,
                producer_completion,
                state: Mutex::new(RequestBodyCompletionState {
                    emitted_bytes: 0,
                    reached_eof: false,
                    failed: false,
                    in_flight_frames: 0,
                    transport_flushed: false,
                    write_timeout: None,
                }),
            }),
        }
    }

    pub(crate) fn is_complete(&self) -> bool {
        let state = self.state();
        self.source_complete(&state)
            && !state.failed
            && state.in_flight_frames == 0
            && state.transport_flushed
    }

    pub(crate) fn is_wire_finished(&self) -> bool {
        self.state().transport_flushed
    }

    pub(crate) fn write_timeout(&self) -> Option<RequestWriteTimeout> {
        self.state().write_timeout.clone()
    }

    pub(crate) fn mark_write_timeout(&self, timeout: RequestWriteTimeout) {
        self.state().write_timeout = Some(timeout);
    }

    fn source_complete(&self, state: &RequestBodyCompletionState) -> bool {
        let body_complete = match self.inner.expected_bytes {
            Some(expected) => state.emitted_bytes == expected,
            None => state.reached_eof,
        };
        body_complete
            && self
                .inner
                .producer_completion
                .as_ref()
                .is_none_or(UploadBodyProducerCompletion::is_finished_and_drained)
    }

    pub(crate) fn mark_transport_flushed(&self) {
        let mut state = self.state();
        let wire_body_ended = match self.inner.expected_bytes {
            Some(expected) => state.emitted_bytes == expected,
            None => state.reached_eof,
        };
        if wire_body_ended && state.in_flight_frames == 0 {
            state.transport_flushed = true;
        }
    }

    fn mark_eof(&self) {
        self.state().reached_eof = true;
    }

    fn track_data(&self, data: Bytes) -> Bytes {
        let data_len = u64::try_from(data.len()).expect("request body frame length fits u64");
        {
            let mut state = self.state();
            state.in_flight_frames += 1;
            state.emitted_bytes = state.emitted_bytes.saturating_add(data_len);
        }
        Bytes::from_owner(TrackedBodyData {
            data,
            completion: self.clone(),
        })
    }

    fn data_consumed(&self) {
        let mut state = self.state();
        debug_assert!(
            state.in_flight_frames > 0,
            "request body frame count underflow"
        );
        state.in_flight_frames = state.in_flight_frames.saturating_sub(1);
        if let Some(producer_completion) = &self.inner.producer_completion {
            producer_completion.data_frame_consumed();
        }
    }

    fn mark_failed(&self) {
        self.state().failed = true;
    }

    fn state(&self) -> MutexGuard<'_, RequestBodyCompletionState> {
        self.inner
            .state
            .lock()
            .expect("request body completion lock poisoned")
    }
}

impl AsRef<[u8]> for TrackedBodyData {
    fn as_ref(&self) -> &[u8] {
        self.data.as_ref()
    }
}

impl Drop for TrackedBodyData {
    fn drop(&mut self) {
        self.completion.data_consumed();
    }
}

impl hyper::body::Body for TrackedRequestBody {
    type Data = Bytes;
    type Error = BodyError;

    fn poll_frame(
        mut self: Pin<&mut Self>,
        context: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Self::Data>, Self::Error>>> {
        match Pin::new(&mut self.body).poll_frame(context) {
            Poll::Ready(Some(Ok(frame))) => {
                let end_stream = self.body.is_end_stream();
                let frame = match frame.into_data() {
                    Ok(data) => Frame::data(self.completion.track_data(data)),
                    Err(frame) => frame,
                };
                if end_stream {
                    self.completion.mark_eof();
                }
                Poll::Ready(Some(Ok(frame)))
            }
            Poll::Ready(Some(Err(error))) => {
                if let Some(timeout) = request_write_timeout_from_error(error.as_ref()) {
                    self.completion.mark_write_timeout(timeout.clone());
                }
                self.completion.mark_failed();
                Poll::Ready(Some(Err(error)))
            }
            Poll::Ready(None) => {
                self.completion.mark_eof();
                Poll::Ready(None)
            }
            Poll::Pending => Poll::Pending,
        }
    }

    fn is_end_stream(&self) -> bool {
        self.body.is_end_stream()
    }

    fn size_hint(&self) -> SizeHint {
        self.body.size_hint()
    }
}

struct StreamingUploadBody {
    receiver: UploadBodyReceiver,
    content_length: Option<u64>,
    write_timeout: Option<RequestWriteTimeoutContext>,
    pending_timeout: Option<Pin<Box<Sleep>>>,
    pending_timeout_started: Option<Instant>,
    finished: bool,
}

impl StreamingUploadBody {
    fn new(
        receiver: UploadBodyReceiver,
        content_length: Option<u64>,
        write_timeout: Option<RequestWriteTimeoutContext>,
    ) -> Self {
        Self {
            receiver,
            content_length,
            write_timeout,
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
        let Some(write_timeout) = self.write_timeout.clone() else {
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
        self.send_blocking_inner(item, false)
    }

    pub(crate) fn send_final_blocking(&self, item: UploadBodyItem) -> bool {
        self.send_blocking_inner(item, true)
    }

    fn send_blocking_inner(&self, item: UploadBodyItem, finish: bool) -> bool {
        let failed = item.is_err();
        let data_frame = item.is_ok();
        let mut state = self.channel.state();
        loop {
            if state.closed {
                return false;
            }
            if state.queue.len() < self.channel.capacity {
                state.queue.push_back(item);
                if data_frame {
                    self.channel.producer_completion.record_data_frame();
                }
                if failed {
                    self.channel.producer_completion.fail();
                }
                if finish {
                    self.channel.producer_completion.finish();
                    state.closed = true;
                }
                let waker = state.receive_waker.take();
                drop(state);
                if finish {
                    self.channel.send_ready.notify_all();
                }
                if let Some(waker) = waker {
                    waker.wake();
                }
                return true;
            }
            state = self.channel.wait_send_ready(state);
        }
    }

    pub(crate) fn send_nowait(&self, item: UploadBodyItem) -> Result<(), UploadBodySendError> {
        self.send_nowait_inner(item, false)
    }

    pub(crate) fn send_final_nowait(
        &self,
        item: UploadBodyItem,
    ) -> Result<(), UploadBodySendError> {
        self.send_nowait_inner(item, true)
    }

    fn send_nowait_inner(
        &self,
        item: UploadBodyItem,
        finish: bool,
    ) -> Result<(), UploadBodySendError> {
        let failed = item.is_err();
        let data_frame = item.is_ok();
        let mut state = self.channel.state();
        if state.closed {
            return Err(UploadBodySendError::Closed);
        }
        if state.queue.len() >= self.channel.capacity {
            return Err(UploadBodySendError::Full);
        }
        state.queue.push_back(item);
        if data_frame {
            self.channel.producer_completion.record_data_frame();
        }
        if failed {
            self.channel.producer_completion.fail();
        }
        if finish {
            self.channel.producer_completion.finish();
            state.closed = true;
        }
        let waker = state.receive_waker.take();
        drop(state);
        if finish {
            self.channel.send_ready.notify_all();
        }
        if let Some(waker) = waker {
            waker.wake();
        }
        Ok(())
    }

    pub(crate) fn close(&self) {
        self.channel.abort();
    }

    pub(crate) fn finish(&self) -> bool {
        self.channel.finish()
    }

    pub(crate) fn is_closed(&self) -> bool {
        self.channel.state().closed
    }

    pub(crate) fn set_ready_callback(&self, callback: Option<ReadyCallback>) {
        self.channel.state().ready_callback = callback;
    }
}

impl UploadBodyReceiver {
    fn producer_completion(&self) -> UploadBodyProducerCompletion {
        self.channel.producer_completion.clone()
    }

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
        self.producer_completion.abort();
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

    fn finish(&self) -> bool {
        let mut state = self.state();
        if state.closed {
            return false;
        }
        self.producer_completion.finish();
        state.closed = true;
        let waker = state.receive_waker.take();
        drop(state);
        self.send_ready.notify_all();
        if let Some(waker) = waker {
            waker.wake();
        }
        true
    }
}

impl UploadBodyProducerCompletion {
    fn new() -> Self {
        Self {
            inner: Arc::new(UploadBodyProducerCompletionInner {
                state: AtomicU8::new(PRODUCER_OPEN),
                outstanding_data_frames: AtomicUsize::new(0),
            }),
        }
    }

    fn record_data_frame(&self) {
        self.inner
            .outstanding_data_frames
            .fetch_add(1, Ordering::AcqRel);
    }

    fn data_frame_consumed(&self) {
        let decremented = self.inner.outstanding_data_frames.fetch_update(
            Ordering::AcqRel,
            Ordering::Acquire,
            |outstanding| outstanding.checked_sub(1),
        );
        debug_assert!(
            decremented.is_ok(),
            "upload body data frame count underflow"
        );
    }

    fn finish(&self) {
        let _ = self.inner.state.compare_exchange(
            PRODUCER_OPEN,
            PRODUCER_FINISHED,
            Ordering::AcqRel,
            Ordering::Acquire,
        );
    }

    fn fail(&self) {
        let _ = self.inner.state.compare_exchange(
            PRODUCER_OPEN,
            PRODUCER_FAILED,
            Ordering::AcqRel,
            Ordering::Acquire,
        );
    }

    fn abort(&self) {
        let _ = self.inner.state.compare_exchange(
            PRODUCER_OPEN,
            PRODUCER_ABORTED,
            Ordering::AcqRel,
            Ordering::Acquire,
        );
    }

    fn is_finished_and_drained(&self) -> bool {
        self.inner.state.load(Ordering::Acquire) == PRODUCER_FINISHED
            && self.inner.outstanding_data_frames.load(Ordering::Acquire) == 0
    }
}

#[cfg(test)]
mod tests {
    use super::{buffered_request_body, streaming_request_body, upload_body_channel};
    use bytes::Bytes;
    use http_body_util::BodyExt;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;
    use tokio::runtime::Builder;

    #[test]
    fn buffered_request_body_reports_completion_after_consumption() {
        let (body, completion) = buffered_request_body(Some(b"request body".to_vec()));
        assert!(!completion.is_complete());

        let collected = Builder::new_current_thread()
            .build()
            .unwrap()
            .block_on(body.collect())
            .unwrap()
            .to_bytes();

        assert_eq!(collected, b"request body".as_slice());
        assert!(!completion.is_complete());
        drop(collected);
        assert!(!completion.is_complete());
        completion.mark_transport_flushed();
        assert!(completion.is_complete());
    }

    #[test]
    fn dropped_request_body_remains_incomplete() {
        let (body, completion) = buffered_request_body(Some(b"request body".to_vec()));

        drop(body);

        assert!(!completion.is_complete());
    }

    #[test]
    fn unknown_length_stream_reports_completion_after_eof_and_consumption() {
        let (sender, receiver) = upload_body_channel(1);
        let (body, completion) = streaming_request_body(receiver, None, None);
        completion.mark_transport_flushed();
        assert_eq!(sender.send_nowait(Ok(Bytes::from_static(b"chunk"))), Ok(()));
        sender.finish();

        let collected = Builder::new_current_thread()
            .build()
            .unwrap()
            .block_on(body.collect())
            .unwrap()
            .to_bytes();

        assert_eq!(collected, b"chunk".as_slice());
        assert!(!completion.is_complete());
        drop(collected);
        assert!(!completion.is_complete());
        completion.mark_transport_flushed();
        assert!(completion.is_complete());
    }

    #[test]
    fn aborted_unknown_length_stream_remains_incomplete_after_transport_flush() {
        let (sender, receiver) = upload_body_channel(1);
        let (body, completion) = streaming_request_body(receiver, None, None);
        sender.close();

        let collected = Builder::new_current_thread()
            .build()
            .unwrap()
            .block_on(body.collect())
            .unwrap()
            .to_bytes();

        assert!(collected.is_empty());
        completion.mark_transport_flushed();
        assert!(!completion.is_complete());
    }

    #[test]
    fn known_length_stream_requires_finished_producer() {
        let (sender, receiver) = upload_body_channel(1);
        let (mut body, completion) = streaming_request_body(receiver, Some(5), None);
        assert_eq!(sender.send_nowait(Ok(Bytes::from_static(b"chunk"))), Ok(()));

        let frame = Builder::new_current_thread()
            .build()
            .unwrap()
            .block_on(body.frame())
            .unwrap()
            .unwrap()
            .into_data()
            .unwrap();
        drop(frame);
        completion.mark_transport_flushed();

        assert!(!completion.is_complete());
        sender.finish();
        assert!(completion.is_complete());
    }

    #[test]
    fn known_length_stream_accepts_atomic_final_chunk() {
        let (sender, receiver) = upload_body_channel(1);
        let (mut body, completion) = streaming_request_body(receiver, Some(5), None);
        assert_eq!(
            sender.send_final_nowait(Ok(Bytes::from_static(b"chunk"))),
            Ok(())
        );

        let frame = Builder::new_current_thread()
            .build()
            .unwrap()
            .block_on(body.frame())
            .unwrap()
            .unwrap()
            .into_data()
            .unwrap();
        drop(frame);
        completion.mark_transport_flushed();

        assert!(completion.is_complete());
    }

    #[test]
    fn known_length_stream_rejects_finished_producer_with_queued_data() {
        let (sender, receiver) = upload_body_channel(2);
        let (mut body, completion) = streaming_request_body(receiver, Some(5), None);
        assert_eq!(sender.send_nowait(Ok(Bytes::from_static(b"chunk"))), Ok(()));
        assert_eq!(
            sender.send_final_nowait(Ok(Bytes::from_static(b"extra"))),
            Ok(())
        );

        let frame = Builder::new_current_thread()
            .build()
            .unwrap()
            .block_on(body.frame())
            .unwrap()
            .unwrap()
            .into_data()
            .unwrap();
        drop(frame);
        completion.mark_transport_flushed();

        assert!(!completion.is_complete());
    }

    #[test]
    fn failed_known_length_stream_remains_incomplete_after_transport_flush() {
        let (sender, receiver) = upload_body_channel(1);
        let (mut body, completion) = streaming_request_body(receiver, Some(5), None);
        assert_eq!(sender.send_nowait(Ok(Bytes::from_static(b"chunk"))), Ok(()));

        let frame = Builder::new_current_thread()
            .build()
            .unwrap()
            .block_on(body.frame())
            .unwrap()
            .unwrap()
            .into_data()
            .unwrap();
        drop(frame);
        assert_eq!(sender.send_nowait(Err("source failed".to_owned())), Ok(()));
        completion.mark_transport_flushed();

        assert!(!completion.is_complete());
    }

    #[test]
    fn aborted_known_length_stream_remains_incomplete_after_transport_flush() {
        let (sender, receiver) = upload_body_channel(1);
        let (mut body, completion) = streaming_request_body(receiver, Some(5), None);
        assert_eq!(sender.send_nowait(Ok(Bytes::from_static(b"chunk"))), Ok(()));

        let frame = Builder::new_current_thread()
            .build()
            .unwrap()
            .block_on(body.frame())
            .unwrap()
            .unwrap()
            .into_data()
            .unwrap();
        drop(frame);
        sender.close();
        completion.mark_transport_flushed();

        assert!(!completion.is_complete());
    }

    #[test]
    fn upload_body_finish_does_not_call_ready_callback() {
        let (sender, _receiver) = upload_body_channel(1);
        let callback_count = Arc::new(AtomicUsize::new(0));
        let callback_count_for_callback = Arc::clone(&callback_count);
        sender.set_ready_callback(Some(Arc::new(move || {
            callback_count_for_callback.fetch_add(1, Ordering::SeqCst);
        })));

        sender.finish();

        assert_eq!(callback_count.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn upload_body_abort_calls_ready_callback() {
        let (sender, _receiver) = upload_body_channel(1);
        let callback_count = Arc::new(AtomicUsize::new(0));
        let callback_count_for_callback = Arc::clone(&callback_count);
        sender.set_ready_callback(Some(Arc::new(move || {
            callback_count_for_callback.fetch_add(1, Ordering::SeqCst);
        })));

        sender.close();

        assert_eq!(callback_count.load(Ordering::SeqCst), 1);
    }
}
