use super::{
    streaming_request_body, upload_body_channel_with_budget, UploadBodyAccount, UploadBodyBudget,
    UploadBodyReceiver, UploadBodySendError, UploadBodySender,
};
use bytes::Bytes;
use http_body_util::BodyExt;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{mpsc, Arc, Barrier};
use std::task::{Context, Poll, Waker};
use std::thread;
use std::time::{Duration, Instant};
use tokio::runtime::Builder;

fn channel(
    capacity: usize,
    upload_limit: usize,
    budget: &Arc<UploadBodyBudget>,
) -> (UploadBodySender, UploadBodyReceiver) {
    upload_body_channel_with_budget(
        capacity,
        Arc::new(UploadBodyAccount::new(upload_limit, Arc::clone(budget))),
    )
}

fn receive(receiver: &mut UploadBodyReceiver) -> Bytes {
    match receiver.poll_recv(&mut Context::from_waker(Waker::noop())) {
        Poll::Ready(Some(Ok(data))) => data,
        other => panic!("expected a queued upload frame, got {other:?}"),
    }
}

fn wait_for_budget_waiter(budget: &UploadBodyBudget) {
    let deadline = Instant::now() + Duration::from_secs(2);
    while budget.waiting_channels() == 0 {
        assert!(
            Instant::now() < deadline,
            "sender did not enter byte admission"
        );
        thread::yield_now();
    }
}

#[test]
fn full_queue_rejects_before_copy_and_preserves_data() {
    let budget = Arc::new(UploadBodyBudget::new(64));
    let (sender, mut receiver) = channel(1, 64, &budget);
    assert_eq!(sender.send_slice_nowait(b"first", false), Ok(()));
    for _ in 0..64 {
        assert_eq!(
            sender.send_slice_nowait(b"next", false),
            Err(UploadBodySendError::Full)
        );
    }
    assert_eq!(budget.copy_count(), 1);
    assert_eq!(budget.buffered_bytes(), 5);
    let first = receive(&mut receiver);
    assert_eq!(first, b"first".as_slice());
    assert_eq!(sender.send_slice_nowait(b"next", false), Ok(()));
    assert_eq!(budget.copy_count(), 2);
    assert_eq!(budget.buffered_bytes(), 9);
    drop(first);
    drop(receive(&mut receiver));
    assert_eq!(budget.buffered_bytes(), 0);
}

#[test]
fn byte_limit_rejects_before_copy_until_last_native_owner_drops() {
    let budget = Arc::new(UploadBodyBudget::new(8));
    let (sender, mut receiver) = channel(2, 8, &budget);
    assert_eq!(sender.send_slice_nowait(b"12345678", false), Ok(()));
    let frame = receive(&mut receiver);
    let cloned = frame.clone();
    let tail = cloned.slice(7..);
    drop(frame);
    drop(cloned);
    for _ in 0..64 {
        assert_eq!(
            sender.send_slice_nowait(b"x", false),
            Err(UploadBodySendError::Full)
        );
    }
    assert_eq!(tail, b"8".as_slice());
    assert_eq!(budget.buffered_bytes(), 8);
    assert_eq!(sender.buffered_bytes(), 8);
    assert_eq!(budget.copy_count(), 1);
    drop(tail);
    assert_eq!(budget.buffered_bytes(), 0);
    assert_eq!(sender.send_slice_nowait(b"recovery", false), Ok(()));
    drop(receive(&mut receiver));
    assert_eq!(budget.buffered_bytes(), 0);
}

#[test]
fn upload_limit_applies_even_when_aggregate_has_capacity() {
    let budget = Arc::new(UploadBodyBudget::new(16));
    let (sender, mut receiver) = channel(2, 4, &budget);
    assert_eq!(sender.send_slice_nowait(b"1234", false), Ok(()));
    let retained = receive(&mut receiver);
    assert_eq!(
        sender.send_slice_nowait(b"x", false),
        Err(UploadBodySendError::Full)
    );
    assert_eq!(budget.copy_count(), 1);
    assert_eq!(budget.buffered_bytes(), 4);
    drop(retained);
    assert_eq!(sender.send_slice_nowait(b"x", false), Ok(()));
    drop(receiver);
    assert_eq!(budget.buffered_bytes(), 0);
}

#[test]
fn aggregate_release_notifies_other_upload_outside_channel_and_budget_locks() {
    let budget = Arc::new(UploadBodyBudget::new(8));
    let (first, mut first_receiver) = channel(2, 8, &budget);
    let (second, mut second_receiver) = channel(2, 8, &budget);
    let callbacks = Arc::new(AtomicUsize::new(0));
    let callback_count = Arc::clone(&callbacks);
    let callback_budget = Arc::clone(&budget);
    let callback_channel = Arc::downgrade(&second.channel);
    second.set_ready_callback(Some(Arc::new(move || {
        let channel = callback_channel.upgrade().unwrap();
        assert!(channel.state.try_lock().is_ok());
        assert_eq!(callback_budget.buffered_bytes(), 0);
        callback_count.fetch_add(1, Ordering::AcqRel);
    })));
    assert_eq!(first.send_slice_nowait(b"12345678", false), Ok(()));
    let retained = receive(&mut first_receiver);
    assert_eq!(
        second.send_slice_nowait(b"x", false),
        Err(UploadBodySendError::Full)
    );
    assert_eq!(callbacks.load(Ordering::Acquire), 0);
    drop(retained);
    assert_eq!(callbacks.load(Ordering::Acquire), 1);
    assert_eq!(second.send_slice_nowait(b"x", false), Ok(()));
    second.set_ready_callback(None);
    drop(receive(&mut second_receiver));
    assert_eq!(budget.buffered_bytes(), 0);
}

#[test]
fn blocked_byte_admission_copies_only_after_release() {
    let budget = Arc::new(UploadBodyBudget::new(8));
    let (first, mut first_receiver) = channel(2, 8, &budget);
    let (second, second_receiver) = channel(2, 8, &budget);
    assert_eq!(first.send_slice_nowait(b"12345678", false), Ok(()));
    let retained = receive(&mut first_receiver);
    let (done, result) = mpsc::channel();
    let handle = thread::spawn(move || {
        done.send(second.send_slice_blocking(b"x", false)).unwrap();
    });
    wait_for_budget_waiter(&budget);
    assert_eq!(budget.copy_count(), 1);
    assert_eq!(budget.buffered_bytes(), 8);
    assert_eq!(result.try_recv(), Err(mpsc::TryRecvError::Empty));
    drop(retained);
    assert!(result.recv_timeout(Duration::from_secs(2)).unwrap());
    handle.join().unwrap();
    assert_eq!(budget.copy_count(), 2);
    assert_eq!(budget.buffered_bytes(), 1);
    drop(second_receiver);
    assert_eq!(budget.buffered_bytes(), 0);
}

#[test]
fn closing_upload_wakes_byte_admission_without_copy() {
    let budget = Arc::new(UploadBodyBudget::new(1));
    let (first, mut first_receiver) = channel(2, 1, &budget);
    let (second, _second_receiver) = channel(2, 1, &budget);
    assert_eq!(first.send_slice_nowait(b"a", false), Ok(()));
    let retained = receive(&mut first_receiver);
    let blocked = second.clone();
    let (done, result) = mpsc::channel();
    let handle = thread::spawn(move || {
        done.send(blocked.send_slice_blocking(b"b", false)).unwrap();
    });
    wait_for_budget_waiter(&budget);
    second.close();
    assert!(!result.recv_timeout(Duration::from_secs(2)).unwrap());
    handle.join().unwrap();
    assert_eq!(budget.copy_count(), 1);
    assert_eq!(budget.buffered_bytes(), 1);
    drop(retained);
    assert_eq!(budget.buffered_bytes(), 0);
}

#[test]
fn closing_finished_upload_releases_queued_bytes_with_owner_retained() {
    let budget = Arc::new(UploadBodyBudget::new(8));
    let (sender, receiver) = channel(2, 8, &budget);
    let (body, completion) = streaming_request_body(receiver, Some(8), None);
    assert_eq!(sender.send_slice_nowait(b"12345678", true), Ok(()));
    assert!(sender.is_closed());
    assert_eq!(budget.buffered_bytes(), 8);
    sender.close();
    assert_eq!(budget.buffered_bytes(), 0);
    assert_eq!(sender.buffered_bytes(), 0);
    let collected = Builder::new_current_thread()
        .build()
        .unwrap()
        .block_on(body.collect())
        .unwrap()
        .to_bytes();
    assert!(collected.is_empty());
    completion.mark_transport_flushed();
    assert!(!completion.is_complete());
    sender.close();
    assert_eq!(budget.buffered_bytes(), 0);
}

#[test]
fn reset_reuses_logical_upload_account_until_previous_frame_drops() {
    let budget = Arc::new(UploadBodyBudget::new(16));
    let account = Arc::new(UploadBodyAccount::new(8, Arc::clone(&budget)));
    let (old, mut old_receiver) = upload_body_channel_with_budget(2, Arc::clone(&account));
    assert_eq!(old.send_slice_nowait(b"12345678", false), Ok(()));
    let old_frame = receive(&mut old_receiver);
    old.close();
    let (current, mut current_receiver) = upload_body_channel_with_budget(2, Arc::clone(&account));
    assert_eq!(
        current.send_slice_nowait(b"x", false),
        Err(UploadBodySendError::Full)
    );
    assert_eq!(account.buffered_bytes(), 8);
    assert_eq!(budget.copy_count(), 1);
    drop(old_frame);
    assert_eq!(account.buffered_bytes(), 0);
    assert_eq!(current.send_slice_nowait(b"x", false), Ok(()));
    assert!(!old.send_slice_blocking(b"stale", false));
    assert_eq!(receive(&mut current_receiver), b"x".as_slice());
    assert_eq!(account.buffered_bytes(), 0);
    assert_eq!(budget.buffered_bytes(), 0);
}

#[test]
fn native_fragment_size_uses_smallest_finite_limit_and_rejects_oversize_before_copy() {
    let budget = Arc::new(UploadBodyBudget::new(1024));
    let (sender, _receiver) = channel(2, 256, &budget);
    assert_eq!(sender.max_chunk_size(), 256);
    let oversized = vec![7; 257];
    assert_eq!(
        sender.send_slice_nowait(&oversized, false),
        Err(UploadBodySendError::Full)
    );
    assert!(!sender.send_slice_blocking(&oversized, false));
    assert_eq!(budget.copy_count(), 0);
    assert_eq!(budget.buffered_bytes(), 0);
    let (large, _receiver) = channel(
        2,
        1024 * 1024,
        &Arc::new(UploadBodyBudget::new(1024 * 1024)),
    );
    assert_eq!(large.max_chunk_size(), 64 * 1024);
}

#[test]
fn concurrent_uploads_share_one_atomic_aggregate_admission() {
    const UPLOADS: usize = 32;
    let budget = Arc::new(UploadBodyBudget::new(8));
    let barrier = Arc::new(Barrier::new(UPLOADS));
    let mut receivers = Vec::new();
    let mut handles = Vec::new();
    for _ in 0..UPLOADS {
        let (sender, receiver) = channel(1, 1, &budget);
        receivers.push(receiver);
        let barrier = Arc::clone(&barrier);
        handles.push(thread::spawn(move || {
            barrier.wait();
            sender.send_slice_nowait(b"x", false).is_ok()
        }));
    }
    let accepted = handles
        .into_iter()
        .map(|handle| handle.join().unwrap())
        .filter(|accepted| *accepted)
        .count();
    assert_eq!(accepted, 8);
    assert_eq!(budget.buffered_bytes(), 8);
    assert_eq!(budget.peak_bytes(), 8);
    assert_eq!(budget.copy_count(), 8);
    drop(receivers);
    assert_eq!(budget.buffered_bytes(), 0);
}

#[test]
fn client_budget_close_aborts_prefilled_and_finished_channels_with_owners_retained() {
    let budget = Arc::new(UploadBodyBudget::new(16));
    let (finished, _finished_receiver) = channel(2, 8, &budget);
    assert_eq!(finished.send_slice_nowait(b"12345678", true), Ok(()));
    let (prefilled, _prefilled_receiver) = channel(2, 8, &budget);
    assert_eq!(prefilled.send_slice_nowait(b"abcdefgh", false), Ok(()));
    assert_eq!(budget.buffered_bytes(), 16);
    budget.close();
    assert!(finished.is_closed());
    assert!(prefilled.is_closed());
    assert_eq!(budget.buffered_bytes(), 0);
    assert_eq!(finished.buffered_bytes(), 0);
    assert_eq!(prefilled.buffered_bytes(), 0);
    assert_eq!(
        prefilled.send_slice_nowait(b"x", false),
        Err(UploadBodySendError::Closed)
    );
    let (late, _late_receiver) = channel(2, 8, &budget);
    assert!(late.is_closed());
    assert!(!late.send_slice_blocking(b"late", false));
    assert_eq!(budget.copy_count(), 2);
    budget.close();
    assert_eq!(budget.buffered_bytes(), 0);
}

#[test]
fn client_budget_close_keeps_in_flight_frame_charged_until_last_drop() {
    let budget = Arc::new(UploadBodyBudget::new(8));
    let (sender, mut receiver) = channel(2, 8, &budget);
    assert_eq!(sender.send_slice_nowait(b"12345678", false), Ok(()));
    let retained = receive(&mut receiver);
    budget.close();
    assert!(sender.is_closed());
    assert_eq!(budget.buffered_bytes(), 8);
    assert_eq!(sender.buffered_bytes(), 8);
    drop(retained);
    assert_eq!(budget.buffered_bytes(), 0);
}
