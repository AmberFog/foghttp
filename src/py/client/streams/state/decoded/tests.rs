use super::super::tests::active_lifecycle_state;
use super::super::{ActiveStreamRead, ReadyFrameCoalescing, StreamState};
use super::DecodedStream;
use crate::core::metrics::Metrics;
use crate::core::response::StreamingDecodePlan;
use crate::errors::{FogHttpLifecycleError, FogHttpResponseDecodingError};
use crate::py::client::acquire::AcquireGate;
use crate::py::client::streams::StreamDecodeOptions;
use bytes::Bytes;
use hyper::header::CONTENT_ENCODING;
use hyper::HeaderMap;
use pyo3::Python;
use std::future::Future;
use std::io::Write;
use std::sync::Arc;
use std::task::{Context, Poll, Waker};
use tokio::runtime::Builder;

const IDENTITY_RESERVATION: usize = 128 * 1024;

async fn decoded_state(input: Bytes, coding: Option<&str>) -> (StreamState, Arc<Metrics>) {
    let (state, metrics, _) = active_lifecycle_state();
    let mut headers = HeaderMap::new();
    if let Some(coding) = coding {
        headers.insert(CONTENT_ENCODING, coding.parse().unwrap());
    }
    let mut decoded = DecodedStream::new(
        StreamingDecodePlan::from_headers(&headers).unwrap(),
        StreamDecodeOptions {
            decode_content: true,
            max_decoded_bytes: None,
            max_memory_bytes: 128 * 1024 * 1024,
        },
        Arc::clone(&metrics),
    )
    .unwrap();
    decoded.input = input;
    let gate = AcquireGate::new(1, None, 1, Arc::clone(&metrics));
    let permit = gate.acquire("http://example.com", 1.0, 0).await.unwrap();
    {
        let mut fields = state.fields();
        fields.decoded_mode = true;
        fields.decoded = Some(decoded);
        fields.permit = Some(permit);
    }
    state.finish_transport_from_read();
    (state, metrics)
}

#[test]
fn post_eof_output_survives_reads_and_holds_admission_until_content_eof() {
    let runtime = Builder::new_current_thread().enable_time().build().unwrap();
    runtime.block_on(async {
        let payload = Bytes::from(vec![42; 20_000]);
        let (state, metrics) = decoded_state(payload.clone(), None).await;
        let mut received = Vec::new();
        loop {
            assert_eq!(metrics.snapshot().active_requests, 1);
            assert_eq!(
                metrics.snapshot().stream_decoder_reserved_bytes,
                IDENTITY_RESERVATION
            );
            let read = state
                .start_read(ReadyFrameCoalescing::Enabled)
                .unwrap()
                .unwrap();
            let chunk = read.read_next_chunk().await.unwrap();
            state.finish_read_delivery();
            let Some(chunk) = chunk else { break };
            received.extend_from_slice(&chunk);
        }
        assert_eq!(received, payload);
        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.active_requests, 0);
        assert_eq!(snapshot.stream_decoder_reserved_bytes, 0);
        assert_eq!(snapshot.failed_requests, 0);
        assert_eq!(snapshot.response_body_closed, 1);
    });
}

#[test]
fn post_eof_client_close_drops_pending_output_and_releases_admission() {
    Python::initialize();
    let runtime = Builder::new_current_thread().enable_time().build().unwrap();
    runtime.block_on(async {
        let (state, metrics) = decoded_state(Bytes::from(vec![7; 20_000]), None).await;
        let read = state
            .start_read(ReadyFrameCoalescing::Enabled)
            .unwrap()
            .unwrap();
        assert!(read.read_next_chunk().await.unwrap().is_some());
        state.finish_read_delivery();
        state.inner.registry.abort_all();
        state.close();
        let error = state
            .start_read(ReadyFrameCoalescing::Enabled)
            .err()
            .unwrap();
        Python::attach(|py| assert!(error.is_instance_of::<FogHttpLifecycleError>(py)));
        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.active_requests, 0);
        assert_eq!(snapshot.stream_decoder_reserved_bytes, 0);
        assert_eq!(snapshot.response_body_aborted, 0);
        assert_eq!(snapshot.failed_requests, 1);
    });
}

#[test]
fn post_eof_truncation_is_typed_failure_not_success() {
    Python::initialize();
    let runtime = Builder::new_current_thread().enable_time().build().unwrap();
    runtime.block_on(async {
        let (state, metrics) = decoded_state(Bytes::new(), Some("gzip")).await;
        let read = state
            .start_read(ReadyFrameCoalescing::Enabled)
            .unwrap()
            .unwrap();
        let error = read.read_next_chunk().await.unwrap_err();
        Python::attach(|py| assert!(error.is_instance_of::<FogHttpResponseDecodingError>(py)));
        state.close();
        state.cancel();
        assert_eq!(state.terminal_error_type(), Some("ResponseDecodingError"));
        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.active_requests, 0);
        assert_eq!(snapshot.stream_decoder_reserved_bytes, 0);
        assert_eq!(snapshot.failed_requests, 1);
        assert_eq!(snapshot.response_body_aborted, 0);
        assert_eq!(snapshot.response_body_closed, 1);
    });
}

#[test]
fn rejected_decoded_read_registration_drops_guard_resources_without_eof() {
    let runtime = Builder::new_current_thread().enable_time().build().unwrap();
    runtime.block_on(async {
        let (state, metrics) = decoded_state(Bytes::from_static(b"pending"), None).await;
        let read = state
            .start_read(ReadyFrameCoalescing::Enabled)
            .unwrap()
            .unwrap();
        let handle = tokio::spawn(async move {
            let _read = read;
            std::future::pending::<()>().await;
        });
        state.cancel();
        assert!(!state.register_read_task(ActiveStreamRead::new_sync(handle.abort_handle())));
        assert!(handle.await.unwrap_err().is_cancelled());
        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.active_requests, 0);
        assert_eq!(snapshot.stream_decoder_reserved_bytes, 0);
        assert_eq!(snapshot.failed_requests, 1);
        assert_eq!(snapshot.response_body_aborted, 0);
    });
}

#[test]
fn decoder_drain_yields_without_network_wait_and_drop_cancels_ownership() {
    let runtime = Builder::new_current_thread().enable_time().build().unwrap();
    runtime.block_on(async {
        let mut encoder = flate2::GzBuilder::new()
            .filename(vec![b'f'; 32_768])
            .write(Vec::new(), flate2::Compression::fast());
        encoder.write_all(b"content").unwrap();
        let input = Bytes::from(encoder.finish().unwrap());
        let (state, metrics) = decoded_state(input, Some("gzip")).await;
        let read = state
            .start_read(ReadyFrameCoalescing::Enabled)
            .unwrap()
            .unwrap();
        let mut future = Box::pin(read.read_next_chunk());
        let mut context = Context::from_waker(Waker::noop());
        assert!(matches!(future.as_mut().poll(&mut context), Poll::Pending));
        assert!(!state.is_finished());
        assert_eq!(metrics.snapshot().active_requests, 1);
        assert!(metrics.snapshot().stream_decoder_reserved_bytes > 0);
        drop(future);
        assert!(state.is_finished());
        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.active_requests, 0);
        assert_eq!(snapshot.stream_decoder_reserved_bytes, 0);
        assert_eq!(snapshot.failed_requests, 1);
        assert_eq!(snapshot.response_body_aborted, 0);
    });
}
