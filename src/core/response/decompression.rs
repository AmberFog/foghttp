use super::body::{enforce_response_body_limit, CollectedBody};
use super::codec::{Codec, CodecStatus, Coding as ContentCoding};
use super::ResponseBodyError;
use crate::core::headers::HeaderPairs;
use hyper::header::CONTENT_ENCODING;
use hyper::HeaderMap;
use std::io;

const DECODE_BUFFER_SIZE: usize = 8192;
const CONTENT_ENCODING_HEADER: &str = "content-encoding";
const CONTENT_LENGTH_HEADER: &str = "content-length";

pub struct ResponseBody {
    pub content: Vec<u8>,
    pub reservation: super::BufferedBodyReservation,
    pub decoded: bool,
}

pub struct ResponseBodyDecodingPlan {
    plan: ContentCodingPlan,
}

impl ResponseBodyDecodingPlan {
    pub fn is_decoding(&self) -> bool {
        matches!(self.plan, ContentCodingPlan::Decode(_))
    }
}

#[derive(Debug, Eq, PartialEq)]
enum ContentCodingPlan {
    Decode(Vec<ContentCoding>),
    LeaveEncoded,
}

pub fn response_body_decoding_plan(headers: &HeaderMap) -> ResponseBodyDecodingPlan {
    ResponseBodyDecodingPlan {
        plan: content_coding_plan(headers),
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BufferedDecodeStatus {
    Progress,
    Finished,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum DecodeAttempt {
    Preferred,
    RawDeflate,
}

struct DecodeLayer {
    coding: ContentCoding,
    codec: Codec,
    offset: usize,
    output: Vec<u8>,
    attempt: DecodeAttempt,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum DecoderState {
    Active,
    Failed,
    Finished,
}

pub struct BufferedBodyDecoder {
    // Release retained codec/output memory before the body's reservation.
    layer: Option<DecodeLayer>,
    codings: Vec<ContentCoding>,
    scratch: Box<[u8]>,
    max_response_body_size: Option<usize>,
    decoded: bool,
    state: DecoderState,
    body: CollectedBody,
    #[cfg(test)]
    completed_layers: usize,
}

impl BufferedBodyDecoder {
    pub fn new(
        body: CollectedBody,
        plan: ResponseBodyDecodingPlan,
        max_response_body_size: Option<usize>,
    ) -> Self {
        let codings = match plan.plan {
            ContentCodingPlan::Decode(codings) => codings,
            ContentCodingPlan::LeaveEncoded => Vec::new(),
        };
        let scratch = if codings.is_empty() {
            Box::default()
        } else {
            vec![0; DECODE_BUFFER_SIZE].into_boxed_slice()
        };
        Self {
            layer: None,
            decoded: !codings.is_empty(),
            state: if codings.is_empty() {
                DecoderState::Finished
            } else {
                DecoderState::Active
            },
            codings,
            scratch,
            max_response_body_size,
            body,
            #[cfg(test)]
            completed_layers: 0,
        }
    }

    /// Each progress result requires a cancellation checkpoint before another
    /// step. One step invokes at most one codec operation with bounded slices.
    pub fn step(&mut self) -> Result<BufferedDecodeStatus, ResponseBodyError> {
        match self.state {
            DecoderState::Finished => return Ok(BufferedDecodeStatus::Finished),
            DecoderState::Failed => {
                return Err(incomplete_decoding("buffered decoding already failed"))
            }
            DecoderState::Active => {}
        }
        let result = self.advance();
        match &result {
            Ok(BufferedDecodeStatus::Finished) => self.state = DecoderState::Finished,
            Err(_) => self.state = DecoderState::Failed,
            Ok(BufferedDecodeStatus::Progress) => {}
        }
        result
    }

    fn advance(&mut self) -> Result<BufferedDecodeStatus, ResponseBodyError> {
        if self.layer.is_none() {
            let Some(coding) = self.codings.pop() else {
                return Ok(BufferedDecodeStatus::Finished);
            };
            self.layer = Some(DecodeLayer {
                coding,
                codec: Codec::buffered(coding, DECODE_BUFFER_SIZE),
                offset: 0,
                output: Vec::new(),
                attempt: DecodeAttempt::Preferred,
            });
        }
        self.step_layer()
    }

    fn step_layer(&mut self) -> Result<BufferedDecodeStatus, ResponseBodyError> {
        let layer = self.layer.as_mut().expect("step owns active decode layer");
        let input = &self.body.content[layer.offset..];
        let offered = input.len().min(DECODE_BUFFER_SIZE);
        // Drain buffered output before reporting truncated input, preserving
        // the reader path's output limit and error ordering.
        let eof = input.is_empty() && layer.coding == ContentCoding::Gzip;
        let result = layer.codec.step(&input[..offered], eof, &mut self.scratch);
        let result = match result {
            Ok(step)
                if input.is_empty()
                    && layer.coding != ContentCoding::Gzip
                    && matches!(step.status, CodecStatus::NeedsInput) =>
            {
                Err(io::Error::new(
                    io::ErrorKind::UnexpectedEof,
                    "truncated content coding",
                ))
            }
            result => result,
        };
        let result = match result {
            Ok(result) => result,
            Err(source) => {
                self.body.reservation.release_chunk(layer.output.len())?;
                layer.output.clear();
                if layer.coding == ContentCoding::Deflate
                    && layer.attempt == DecodeAttempt::Preferred
                    && !has_zlib_header(&self.body.content)
                {
                    layer.codec = Codec::raw_deflate();
                    layer.attempt = DecodeAttempt::RawDeflate;
                    layer.offset = 0;
                    return Ok(BufferedDecodeStatus::Progress);
                }
                return Err(ResponseBodyError::Decode {
                    coding: layer.coding.name(),
                    source,
                });
            }
        };
        layer.offset += result.consumed;
        if let Err(error) = enforce_response_body_limit(
            layer.output.len(),
            result.produced,
            self.max_response_body_size,
        )
        .and_then(|()| {
            layer
                .output
                .len()
                .checked_add(result.produced)
                .ok_or(ResponseBodyError::DecodeReservationOverflow)?;
            self.body.reservation.reserve_chunk(result.produced)
        }) {
            self.body.reservation.release_chunk(layer.output.len())?;
            layer.output.clear();
            return Err(error);
        }
        layer
            .output
            .extend_from_slice(&self.scratch[..result.produced]);
        if matches!(result.status, CodecStatus::Ended) {
            let encoded_size = self.body.content.len();
            self.body.content = std::mem::take(&mut layer.output);
            self.body.reservation.release_chunk(encoded_size)?;
            self.layer = None;
            #[cfg(test)]
            {
                self.completed_layers += 1;
            }
            if self.codings.is_empty() {
                return Ok(BufferedDecodeStatus::Finished);
            }
        }
        Ok(BufferedDecodeStatus::Progress)
    }

    pub fn finish(self) -> Result<ResponseBody, ResponseBodyError> {
        if self.state != DecoderState::Finished {
            return Err(incomplete_decoding("unfinished buffered decoding"));
        }
        Ok(ResponseBody {
            content: self.body.content,
            reservation: self.body.reservation,
            decoded: self.decoded,
        })
    }

    #[cfg(test)]
    pub fn test_progress(&self) -> BufferedDecodeProgress {
        BufferedDecodeProgress {
            completed_layers: self.completed_layers,
            remaining_layers: self.codings.len(),
            output_bytes: self.layer.as_ref().map_or(0, |layer| layer.output.len()),
            raw_deflate: self
                .layer
                .as_ref()
                .is_some_and(|layer| layer.attempt == DecodeAttempt::RawDeflate),
        }
    }
}

#[cfg(test)]
#[derive(Clone, Copy, Debug)]
pub struct BufferedDecodeProgress {
    pub completed_layers: usize,
    pub remaining_layers: usize,
    pub output_bytes: usize,
    pub raw_deflate: bool,
}

fn incomplete_decoding(reason: &'static str) -> ResponseBodyError {
    ResponseBodyError::Decode {
        coding: "response body",
        source: io::Error::new(io::ErrorKind::UnexpectedEof, reason),
    }
}

pub fn decoded_response_headers(headers: HeaderPairs, decoded: bool) -> HeaderPairs {
    if !decoded {
        return headers;
    }

    headers
        .into_iter()
        .filter(|(name, _value)| !decoded_body_header(name))
        .collect()
}

fn content_coding_plan(headers: &HeaderMap) -> ContentCodingPlan {
    let mut codings = Vec::new();
    for value in &headers.get_all(CONTENT_ENCODING) {
        let Ok(value) = value.to_str() else {
            return ContentCodingPlan::LeaveEncoded;
        };
        for item in value.split(',') {
            let coding = item.trim().to_ascii_lowercase();
            if coding.is_empty() || coding == "identity" {
                continue;
            }
            let Some(supported) = supported_content_coding(&coding) else {
                return ContentCodingPlan::LeaveEncoded;
            };
            codings.push(supported);
        }
    }

    if codings.is_empty() {
        ContentCodingPlan::LeaveEncoded
    } else {
        ContentCodingPlan::Decode(codings)
    }
}

fn supported_content_coding(coding: &str) -> Option<ContentCoding> {
    match coding {
        "gzip" | "x-gzip" => Some(ContentCoding::Gzip),
        "deflate" => Some(ContentCoding::Deflate),
        "br" => Some(ContentCoding::Brotli),
        _unknown => None,
    }
}

fn has_zlib_header(content: &[u8]) -> bool {
    let Some(&[method, flags]) = content.first_chunk::<2>() else {
        return false;
    };
    method & 0x0f == 8 && method >> 4 <= 7 && u16::from_be_bytes([method, flags]) % 31 == 0
}

fn decoded_body_header(name: &str) -> bool {
    name.eq_ignore_ascii_case(CONTENT_ENCODING_HEADER)
        || name.eq_ignore_ascii_case(CONTENT_LENGTH_HEADER)
}

#[cfg(test)]
mod tests;
