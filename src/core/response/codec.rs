mod gzip;

use brotli::{BrotliDecompressStream, BrotliResult, BrotliState, HeapAlloc, HuffmanCode};
use flate2::{Decompress, FlushDecompress, Status};
use gzip::Gzip;
use std::io;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum Coding {
    Gzip,
    Deflate,
    Brotli,
}

impl Coding {
    pub(super) fn name(self) -> &'static str {
        match self {
            Self::Gzip => "gzip",
            Self::Deflate => "deflate",
            Self::Brotli => "br",
        }
    }
}

type BrotliDecoder = BrotliState<HeapAlloc<u8>, HeapAlloc<u32>, HeapAlloc<HuffmanCode>>;

pub(super) enum Codec {
    Gzip(Box<Gzip>),
    Deflate(Decompress),
    Brotli(Box<BrotliDecoder>),
}

pub(super) enum CodecStatus {
    NeedsInput,
    Progress,
    Ended,
}

pub(super) struct CodecStep {
    pub consumed: usize,
    pub produced: usize,
    pub status: CodecStatus,
}

impl Codec {
    pub(super) fn new(coding: Coding, output_capacity: usize) -> Self {
        match coding {
            Coding::Gzip => Self::Gzip(Box::new(Gzip::new(output_capacity))),
            Coding::Deflate => Self::Deflate(Decompress::new(true)),
            Coding::Brotli => Self::Brotli(Box::new(BrotliState::new_strict(
                HeapAlloc::default(),
                HeapAlloc::default(),
                HeapAlloc::default(),
            ))),
        }
    }

    pub(super) fn buffered(coding: Coding, output_capacity: usize) -> Self {
        match coding {
            Coding::Brotli => Self::Brotli(Box::new(BrotliState::new(
                HeapAlloc::default(),
                HeapAlloc::default(),
                HeapAlloc::default(),
            ))),
            _ => Self::new(coding, output_capacity),
        }
    }

    pub(super) fn raw_deflate() -> Self {
        Self::Deflate(Decompress::new(false))
    }

    pub(super) fn step(
        &mut self,
        input: &[u8],
        eof: bool,
        output: &mut [u8],
    ) -> io::Result<CodecStep> {
        match self {
            Self::Gzip(decoder) => decoder.step(input, eof, output),
            Self::Deflate(decoder) => {
                let before_in = decoder.total_in();
                let before_out = decoder.total_out();
                let result = decoder
                    .decompress(input, output, FlushDecompress::None)
                    .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
                let consumed = usize::try_from(decoder.total_in() - before_in)
                    .map_err(|_| invalid("codec byte counter overflow"))?;
                let produced = usize::try_from(decoder.total_out() - before_out)
                    .map_err(|_| invalid("codec byte counter overflow"))?;
                let status = if result == Status::StreamEnd {
                    CodecStatus::Ended
                } else if produced != 0 || (consumed != 0 && consumed < input.len()) {
                    CodecStatus::Progress
                } else if consumed == input.len() {
                    if eof {
                        return Err(truncated());
                    }
                    CodecStatus::NeedsInput
                } else {
                    return Err(invalid("decoder made no progress"));
                };
                Ok(CodecStep {
                    consumed,
                    produced,
                    status,
                })
            }
            Self::Brotli(decoder) => {
                let mut available_in = input.len();
                let mut consumed = 0;
                let mut available_out = output.len();
                let mut produced = 0;
                // The pipeline owns cumulative checked counters. This API's
                // total_out is an output parameter, never an input limit.
                let mut total_out = 0;
                let result = BrotliDecompressStream(
                    &mut available_in,
                    &mut consumed,
                    input,
                    &mut available_out,
                    &mut produced,
                    output,
                    &mut total_out,
                    decoder,
                );
                let status = match result {
                    BrotliResult::ResultSuccess => CodecStatus::Ended,
                    BrotliResult::ResultFailure => return Err(invalid("invalid Brotli stream")),
                    BrotliResult::NeedsMoreInput => {
                        if eof {
                            return Err(truncated());
                        }
                        // Brotli can still have ring-buffer output pending.
                        if produced != 0 {
                            CodecStatus::Progress
                        } else {
                            CodecStatus::NeedsInput
                        }
                    }
                    BrotliResult::NeedsMoreOutput => {
                        if consumed == 0 && produced == 0 {
                            return Err(invalid("decoder made no progress"));
                        }
                        CodecStatus::Progress
                    }
                };
                Ok(CodecStep {
                    consumed,
                    produced,
                    status,
                })
            }
        }
    }
}

fn invalid(reason: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, reason)
}

fn truncated() -> io::Error {
    io::Error::new(io::ErrorKind::UnexpectedEof, "truncated content coding")
}
