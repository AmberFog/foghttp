use super::constants::{MAX_READY_FRAME_COALESCE_COUNT, READY_FRAME_COALESCE_TARGET_BYTES};
use bytes::{Bytes, BytesMut};
use hyper::body::{Body, Incoming};
use std::pin::Pin;
use std::task::{Context, Poll, Waker};

pub(super) enum ReadyFrameDrain {
    Eof,
    Error(String),
    Stopped,
}

enum ReadyBodyFrame {
    Data(Bytes),
    Eof,
    Pending,
    Error(String),
}

pub(super) fn drain_ready_data_frames(chunk: &mut Bytes, body: &mut Incoming) -> ReadyFrameDrain {
    drain_ready_data_frames_with(chunk, || poll_ready_body_frame(body))
}

fn poll_ready_body_frame(body: &mut Incoming) -> ReadyBodyFrame {
    let waker = Waker::noop();
    let mut context = Context::from_waker(waker);
    loop {
        let frame = match Pin::new(&mut *body).poll_frame(&mut context) {
            Poll::Ready(frame) => frame,
            Poll::Pending => return ReadyBodyFrame::Pending,
        };
        let Some(frame) = frame else {
            return ReadyBodyFrame::Eof;
        };
        let frame = match frame {
            Ok(frame) => frame,
            Err(err) => return ReadyBodyFrame::Error(err.to_string()),
        };
        let Ok(data) = frame.into_data() else {
            continue;
        };
        return ReadyBodyFrame::Data(data);
    }
}

fn drain_ready_data_frames_with(
    chunk: &mut Bytes,
    mut poll_ready_body_frame: impl FnMut() -> ReadyBodyFrame,
) -> ReadyFrameDrain {
    let mut coalesced_frames = 1;
    let mut merged: Option<BytesMut> = None;
    let outcome = loop {
        let chunk_len = merged.as_ref().map_or(chunk.len(), BytesMut::len);
        if chunk_len >= READY_FRAME_COALESCE_TARGET_BYTES
            || coalesced_frames >= MAX_READY_FRAME_COALESCE_COUNT
        {
            break ReadyFrameDrain::Stopped;
        }
        match poll_ready_body_frame() {
            ReadyBodyFrame::Data(data) => {
                let buffer = merged.get_or_insert_with(|| {
                    let mut buffer = BytesMut::with_capacity(chunk.len() + data.len());
                    buffer.extend_from_slice(chunk);
                    buffer
                });
                buffer.extend_from_slice(&data);
                coalesced_frames += 1;
            }
            ReadyBodyFrame::Eof => break ReadyFrameDrain::Eof,
            ReadyBodyFrame::Error(error) => break ReadyFrameDrain::Error(error),
            ReadyBodyFrame::Pending => break ReadyFrameDrain::Stopped,
        }
    };
    if let Some(merged) = merged {
        *chunk = merged.freeze();
    }
    outcome
}

#[cfg(test)]
mod tests;
