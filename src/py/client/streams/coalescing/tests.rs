use super::{drain_ready_data_frames_with, ReadyBodyFrame, ReadyFrameDrain};
use crate::py::client::streams::constants::{
    MAX_READY_FRAME_COALESCE_COUNT, READY_FRAME_COALESCE_TARGET_BYTES,
};
use bytes::Bytes;
use pyo3::prelude::*;
use std::collections::VecDeque;
use std::sync::Once;

fn initialize_python() {
    static PYTHON: Once = Once::new();
    PYTHON.call_once(Python::initialize);
}

#[test]
fn ready_frame_coalescing_merges_ready_data_until_eof() {
    let mut chunk = Bytes::from_static(b"first");
    let mut frames = VecDeque::from([
        ReadyBodyFrame::Data(Bytes::from_static(b"second")),
        ReadyBodyFrame::Data(Bytes::from_static(b"third")),
        ReadyBodyFrame::Eof,
    ]);

    let outcome = drain_ready_data_frames_with(&mut chunk, || frames.pop_front().unwrap());

    assert!(matches!(outcome, ReadyFrameDrain::Eof));
    assert_eq!(chunk.as_ref(), b"firstsecondthird");
}

#[test]
fn ready_frame_coalescing_stops_on_pending_without_consuming_later_frames() {
    let mut chunk = Bytes::from_static(b"first");
    let mut frames = VecDeque::from([
        ReadyBodyFrame::Data(Bytes::from_static(b"second")),
        ReadyBodyFrame::Pending,
        ReadyBodyFrame::Data(Bytes::from_static(b"third")),
    ]);

    let outcome = drain_ready_data_frames_with(&mut chunk, || frames.pop_front().unwrap());

    assert!(matches!(outcome, ReadyFrameDrain::Stopped));
    assert_eq!(chunk.as_ref(), b"firstsecond");
    assert!(matches!(frames.pop_front(), Some(ReadyBodyFrame::Data(_))));
}

#[test]
fn ready_frame_coalescing_returns_collected_data_before_deferred_error() {
    let mut chunk = Bytes::from_static(b"first");
    let mut frames = VecDeque::from([
        ReadyBodyFrame::Data(Bytes::from_static(b"second")),
        ReadyBodyFrame::Error("broken body".to_string()),
    ]);

    let outcome = drain_ready_data_frames_with(&mut chunk, || frames.pop_front().unwrap());

    assert!(matches!(outcome, ReadyFrameDrain::Error(error) if error == "broken body"));
    assert_eq!(chunk.as_ref(), b"firstsecond");
}

#[test]
fn ready_frame_coalescing_respects_count_and_byte_targets() {
    let mut chunk = Bytes::new();
    let mut poll_count = 0;
    let outcome = drain_ready_data_frames_with(&mut chunk, || {
        poll_count += 1;
        ReadyBodyFrame::Data(Bytes::from_static(b"x"))
    });

    assert!(matches!(outcome, ReadyFrameDrain::Stopped));
    assert_eq!(poll_count, MAX_READY_FRAME_COALESCE_COUNT - 1);
    assert_eq!(chunk.len(), MAX_READY_FRAME_COALESCE_COUNT - 1);

    let mut chunk = Bytes::from(vec![b'a'; READY_FRAME_COALESCE_TARGET_BYTES - 1]);
    let mut poll_count = 0;
    let outcome = drain_ready_data_frames_with(&mut chunk, || {
        poll_count += 1;
        ReadyBodyFrame::Data(Bytes::from_static(b"xy"))
    });

    assert!(matches!(outcome, ReadyFrameDrain::Stopped));
    assert_eq!(poll_count, 1);
    assert_eq!(chunk.len(), READY_FRAME_COALESCE_TARGET_BYTES + 1);
}

#[test]
#[ignore = "manual release-mode boundary measurement; no timing assertion"]
fn measure_streaming_boundary_conversion() {
    use pyo3::types::PyBytes;
    use std::hint::black_box;
    use std::time::Instant;

    initialize_python();
    Python::attach(|py| {
        for size in [4096, 65_536, 262_144] {
            for frames in [1, 2] {
                let data = Bytes::from(vec![b'x'; size / frames]);
                let iterations = u32::try_from(256 * 1024 * 1024 / size).unwrap();
                for warmup in [true, false] {
                    let start = Instant::now();
                    for _ in 0..iterations {
                        // Match the initial frame handoff in read_next_chunk.
                        let mut chunk = black_box(&data).clone();
                        let mut remaining = frames - 1;
                        let outcome = drain_ready_data_frames_with(&mut chunk, || {
                            if remaining == 0 {
                                ReadyBodyFrame::Pending
                            } else {
                                remaining -= 1;
                                ReadyBodyFrame::Data(data.clone())
                            }
                        });
                        black_box(outcome);
                        black_box(PyBytes::new(py, &chunk));
                    }
                    if !warmup {
                        println!(
                            "boundary size={size} frames={frames} iterations={iterations} ns_per_chunk={:.1}",
                            start.elapsed().as_secs_f64() * 1e9 / f64::from(iterations),
                        );
                    }
                }
            }
        }
    });
}

#[test]
fn single_ready_frame_keeps_owned_storage_until_python_conversion() {
    for frame in [
        ReadyBodyFrame::Pending,
        ReadyBodyFrame::Eof,
        ReadyBodyFrame::Error("broken body".to_string()),
    ] {
        let owner = Bytes::from(vec![b'x'; 4096]);
        let mut chunk = owner.slice(10..20);
        let original = chunk.as_ptr();
        let mut frame = Some(frame);
        let _ = drain_ready_data_frames_with(&mut chunk, || frame.take().unwrap());
        drop(owner);

        assert_eq!(chunk.as_ptr(), original);
        assert_eq!(chunk.as_ref(), &[b'x'; 10]);
    }
}

#[test]
fn ready_frame_at_byte_target_is_not_polled_or_copied() {
    for size in [
        READY_FRAME_COALESCE_TARGET_BYTES,
        READY_FRAME_COALESCE_TARGET_BYTES + 1,
    ] {
        let mut chunk = Bytes::from(vec![b'x'; size]);
        let original = chunk.as_ptr();
        let outcome = drain_ready_data_frames_with(&mut chunk, || panic!("must not poll"));

        assert!(matches!(outcome, ReadyFrameDrain::Stopped));
        assert_eq!(chunk.as_ptr(), original);
        assert_eq!(chunk.len(), size);
    }
}
