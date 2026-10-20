use super::body::{enforce_response_body_limit, CollectedBody};
use super::ResponseBodyError;
use crate::core::headers::HeaderPairs;
use brotli::Decompressor;
use flate2::read::MultiGzDecoder;
use flate2::{Decompress, FlushDecompress, Status};
use hyper::header::CONTENT_ENCODING;
use hyper::HeaderMap;
use std::io::{Cursor, Read};

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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ContentCoding {
    Gzip,
    Deflate,
    Brotli,
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

pub fn decode_body(
    collected: CollectedBody,
    decoding_plan: ResponseBodyDecodingPlan,
    max_response_body_size: Option<usize>,
) -> Result<ResponseBody, ResponseBodyError> {
    match decoding_plan.plan {
        ContentCodingPlan::Decode(codings) => {
            decode_supported_body(collected, codings.as_slice(), max_response_body_size)
        }
        ContentCodingPlan::LeaveEncoded => Ok(ResponseBody {
            content: collected.content,
            reservation: collected.reservation,
            decoded: false,
        }),
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

fn decode_supported_body(
    mut body: CollectedBody,
    codings: &[ContentCoding],
    max_response_body_size: Option<usize>,
) -> Result<ResponseBody, ResponseBodyError> {
    let mut content = std::mem::take(&mut body.content);
    for coding in codings.iter().rev().copied() {
        let encoded_size = content.len();
        content = decode_content_coding(
            coding,
            &content,
            max_response_body_size,
            &mut body.reservation,
        )?;
        body.reservation.release_chunk(encoded_size)?;
    }

    Ok(ResponseBody {
        content,
        reservation: body.reservation,
        decoded: true,
    })
}

fn decode_content_coding(
    coding: ContentCoding,
    content: &[u8],
    max_response_body_size: Option<usize>,
    reservation: &mut super::BufferedBodyReservation,
) -> Result<Vec<u8>, ResponseBodyError> {
    match coding {
        ContentCoding::Gzip => decode_reader(
            coding,
            MultiGzDecoder::new(Cursor::new(content)),
            max_response_body_size,
            reservation,
        ),
        ContentCoding::Deflate => decode_deflate(content, max_response_body_size, reservation),
        ContentCoding::Brotli => decode_reader(
            coding,
            Decompressor::new(Cursor::new(content), DECODE_BUFFER_SIZE),
            max_response_body_size,
            reservation,
        ),
    }
}

fn decode_deflate(
    content: &[u8],
    max_response_body_size: Option<usize>,
    reservation: &mut super::BufferedBodyReservation,
) -> Result<Vec<u8>, ResponseBodyError> {
    match decode_reader_result(
        CompleteDeflateDecoder::new(content, Decompress::new(true)),
        max_response_body_size,
        reservation,
    ) {
        Ok(decoded) => Ok(decoded),
        Err(DecodeAttemptError::Read(_err)) if !has_zlib_header(content) => decode_reader(
            ContentCoding::Deflate,
            CompleteDeflateDecoder::new(content, Decompress::new(false)),
            max_response_body_size,
            reservation,
        ),
        Err(err) => Err(decode_attempt_error(ContentCoding::Deflate, err)),
    }
}

fn has_zlib_header(content: &[u8]) -> bool {
    let Some(&[method, flags]) = content.first_chunk::<2>() else {
        return false;
    };
    method & 0x0f == 8 && method >> 4 <= 7 && u16::from_be_bytes([method, flags]) % 31 == 0
}

struct CompleteDeflateDecoder<'a> {
    input: &'a [u8],
    decoder: Decompress,
    finished: bool,
}

impl<'a> CompleteDeflateDecoder<'a> {
    fn new(input: &'a [u8], decoder: Decompress) -> Self {
        Self {
            input,
            decoder,
            finished: false,
        }
    }
}

impl Read for CompleteDeflateDecoder<'_> {
    fn read(&mut self, output: &mut [u8]) -> std::io::Result<usize> {
        if self.finished || output.is_empty() {
            return Ok(0);
        }

        loop {
            let before_in = self.decoder.total_in();
            let before_out = self.decoder.total_out();
            let status = self
                .decoder
                .decompress(self.input, output, FlushDecompress::None)
                .map_err(|error| std::io::Error::new(std::io::ErrorKind::InvalidData, error))?;
            let consumed = usize::try_from(self.decoder.total_in() - before_in)
                .map_err(std::io::Error::other)?;
            let produced = usize::try_from(self.decoder.total_out() - before_out)
                .map_err(std::io::Error::other)?;
            self.input = &self.input[consumed..];
            self.finished = status == Status::StreamEnd;
            if produced != 0 || self.finished {
                return Ok(produced);
            }
            if consumed == 0 {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::UnexpectedEof,
                    "truncated deflate stream",
                ));
            }
        }
    }
}

fn decode_reader<R: Read>(
    coding: ContentCoding,
    reader: R,
    max_response_body_size: Option<usize>,
    reservation: &mut super::BufferedBodyReservation,
) -> Result<Vec<u8>, ResponseBodyError> {
    decode_reader_result(reader, max_response_body_size, reservation)
        .map_err(|err| decode_attempt_error(coding, err))
}

enum DecodeAttemptError {
    Read(std::io::Error),
    Runtime(ResponseBodyError),
}

fn decode_reader_result<R: Read>(
    mut reader: R,
    max_response_body_size: Option<usize>,
    reservation: &mut super::BufferedBodyReservation,
) -> Result<Vec<u8>, DecodeAttemptError> {
    let mut decoded = Vec::new();
    let mut buffer = [0_u8; DECODE_BUFFER_SIZE];
    let mut attempt_reserved = 0_usize;

    loop {
        let read = match reader.read(&mut buffer) {
            Ok(read) => read,
            Err(err) => {
                if let Err(release_error) = reservation.release_chunk(attempt_reserved) {
                    return Err(DecodeAttemptError::Runtime(release_error));
                }
                return Err(DecodeAttemptError::Read(err));
            }
        };
        if read == 0 {
            return Ok(decoded);
        }

        if let Err(err) = enforce_response_body_limit(decoded.len(), read, max_response_body_size) {
            if let Err(release_error) = reservation.release_chunk(attempt_reserved) {
                return Err(DecodeAttemptError::Runtime(release_error));
            }
            return Err(DecodeAttemptError::Runtime(err));
        }
        if let Err(err) = reservation.reserve_chunk(read) {
            if let Err(release_error) = reservation.release_chunk(attempt_reserved) {
                return Err(DecodeAttemptError::Runtime(release_error));
            }
            return Err(DecodeAttemptError::Runtime(err));
        }
        let Some(next_attempt_reserved) = attempt_reserved.checked_add(read) else {
            if let Err(release_error) = reservation.release_chunk(attempt_reserved) {
                return Err(DecodeAttemptError::Runtime(release_error));
            }
            return Err(DecodeAttemptError::Runtime(
                ResponseBodyError::DecodeReservationOverflow,
            ));
        };
        attempt_reserved = next_attempt_reserved;
        decoded.extend_from_slice(&buffer[..read]);
    }
}

fn decode_attempt_error(coding: ContentCoding, err: DecodeAttemptError) -> ResponseBodyError {
    match err {
        DecodeAttemptError::Read(source) => ResponseBodyError::Decode {
            coding: content_coding_name(coding),
            source,
        },
        DecodeAttemptError::Runtime(err) => err,
    }
}

fn content_coding_name(coding: ContentCoding) -> &'static str {
    match coding {
        ContentCoding::Gzip => "gzip",
        ContentCoding::Deflate => "deflate",
        ContentCoding::Brotli => "br",
    }
}

fn decoded_body_header(name: &str) -> bool {
    name.eq_ignore_ascii_case(CONTENT_ENCODING_HEADER)
        || name.eq_ignore_ascii_case(CONTENT_LENGTH_HEADER)
}

#[cfg(test)]
mod tests;
