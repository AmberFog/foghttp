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
