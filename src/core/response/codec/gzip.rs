use super::{CodecStatus, CodecStep};
use flate2::write::MultiGzDecoder;
use std::io::{self, Write};

pub(in crate::core::response) struct Gzip {
    decoder: MultiGzDecoder<Output>,
    flush_pending: bool,
}

impl Gzip {
    pub(super) fn new(output_capacity: usize) -> Self {
        Self {
            decoder: MultiGzDecoder::new(Output {
                bytes: vec![0; output_capacity].into_boxed_slice(),
                position: 0,
                limit: output_capacity,
            }),
            flush_pending: false,
        }
    }

    pub(super) fn step(
        &mut self,
        input: &[u8],
        eof: bool,
        output: &mut [u8],
    ) -> io::Result<CodecStep> {
        let sink = self.decoder.get_mut();
        sink.position = 0;
        sink.limit = output.len();

        // Each step invokes one library operation. Drain with flush, not fake
        // input EOF: the bufread adapter cannot drain miniz on WouldBlock.
        let result = if self.flush_pending {
            self.decoder.flush().map(|()| {
                self.flush_pending = false;
                (0, CodecStatus::NeedsInput)
            })
        } else if input.is_empty() {
            if eof {
                self.decoder.try_finish().map(|()| (0, CodecStatus::Ended))
            } else {
                Ok((0, CodecStatus::NeedsInput))
            }
        } else {
            self.decoder.write(input).map(|consumed| {
                self.flush_pending = true;
                (consumed, CodecStatus::Progress)
            })
        };
        let (consumed, status) = match result {
            Ok(result) => result,
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                // flate2 dumps pending output before accepting more input;
                // a blocked write therefore consumes no supplied input.
                self.flush_pending = true;
                (0, CodecStatus::Progress)
            }
            Err(error) => return Err(error),
        };
        let sink = self.decoder.get_ref();
        let produced = sink.position;
        if consumed == 0 && produced == 0 && matches!(status, CodecStatus::Progress) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "gzip decoder made no progress",
            ));
        }
        output[..produced].copy_from_slice(&sink.bytes[..produced]);
        Ok(CodecStep {
            consumed,
            produced,
            status,
        })
    }
}

impl Drop for Gzip {
    fn drop(&mut self) {
        // flate2 writers attempt a flush on drop. Refuse pending output during
        // cleanup so abandonment cannot drain an arbitrarily expanding body.
        let sink = self.decoder.get_mut();
        sink.position = 0;
        sink.limit = 0;
    }
}

struct Output {
    bytes: Box<[u8]>,
    position: usize,
    limit: usize,
}

impl Write for Output {
    fn write(&mut self, input: &[u8]) -> io::Result<usize> {
        let count = input.len().min(self.limit - self.position);
        if count == 0 && !input.is_empty() {
            return Err(io::ErrorKind::WouldBlock.into());
        }
        self.bytes[self.position..self.position + count].copy_from_slice(&input[..count]);
        self.position += count;
        Ok(count)
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
