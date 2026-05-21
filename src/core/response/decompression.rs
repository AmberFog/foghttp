use super::body::{enforce_response_body_limit, CollectedBody};
use crate::core::headers::HeaderPairs;
use crate::errors::FogHttpError;
use brotli::Decompressor;
use flate2::read::{DeflateDecoder, MultiGzDecoder, ZlibDecoder};
use pyo3::prelude::*;
use std::io::{Cursor, Read};

const DECODE_BUFFER_SIZE: usize = 8192;
const CONTENT_ENCODING: &str = "content-encoding";
const CONTENT_LENGTH: &str = "content-length";

pub struct ResponseBody {
    pub content: Vec<u8>,
    pub reservation: super::BufferedBodyReservation,
    pub decoded: bool,
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

pub fn decode_body(
    collected: CollectedBody,
    headers: &HeaderPairs,
    max_response_body_size: Option<usize>,
) -> PyResult<ResponseBody> {
    match content_coding_plan(headers) {
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

fn content_coding_plan(headers: &HeaderPairs) -> ContentCodingPlan {
    let mut codings = Vec::new();
    for (_name, value) in headers
        .iter()
        .filter(|(name, _value)| name.eq_ignore_ascii_case(CONTENT_ENCODING))
    {
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
) -> PyResult<ResponseBody> {
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
) -> PyResult<Vec<u8>> {
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
) -> PyResult<Vec<u8>> {
    match decode_reader_result(
        ZlibDecoder::new(Cursor::new(content)),
        max_response_body_size,
        reservation,
    ) {
        Ok(decoded) => Ok(decoded),
        Err(DecodeAttemptError::Read(_err)) => decode_reader(
            ContentCoding::Deflate,
            DeflateDecoder::new(Cursor::new(content)),
            max_response_body_size,
            reservation,
        ),
        Err(DecodeAttemptError::Runtime(err)) => Err(err),
    }
}

fn decode_reader<R: Read>(
    coding: ContentCoding,
    reader: R,
    max_response_body_size: Option<usize>,
    reservation: &mut super::BufferedBodyReservation,
) -> PyResult<Vec<u8>> {
    decode_reader_result(reader, max_response_body_size, reservation)
        .map_err(|err| decode_attempt_error(coding, err))
}

enum DecodeAttemptError {
    Read(std::io::Error),
    Runtime(PyErr),
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
            return Err(DecodeAttemptError::Runtime(FogHttpError::new_err(
                "decoded response byte reservation overflow",
            )));
        };
        attempt_reserved = next_attempt_reserved;
        decoded.extend_from_slice(&buffer[..read]);
    }
}

fn decode_attempt_error(coding: ContentCoding, err: DecodeAttemptError) -> PyErr {
    match err {
        DecodeAttemptError::Read(err) => FogHttpError::new_err(format!(
            "failed to decode {} response body: {err}",
            content_coding_name(coding),
        )),
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
    name.eq_ignore_ascii_case(CONTENT_ENCODING) || name.eq_ignore_ascii_case(CONTENT_LENGTH)
}

#[cfg(test)]
mod tests {
    use super::{content_coding_plan, decoded_response_headers, ContentCoding, ContentCodingPlan};

    #[test]
    fn content_coding_plan_supports_multiple_encodings() {
        let plan = content_coding_plan(&vec![(
            "content-encoding".to_owned(),
            "gzip, br".to_owned(),
        )]);

        assert_eq!(
            plan,
            ContentCodingPlan::Decode(vec![ContentCoding::Gzip, ContentCoding::Brotli]),
        );
    }

    #[test]
    fn content_coding_plan_leaves_unknown_encoding_untouched() {
        let plan = content_coding_plan(&vec![("content-encoding".to_owned(), "zstd".to_owned())]);

        assert_eq!(plan, ContentCodingPlan::LeaveEncoded);
    }

    #[test]
    fn decoded_response_headers_remove_consumed_body_headers() {
        let headers = decoded_response_headers(
            vec![
                ("content-type".to_owned(), "text/plain".to_owned()),
                ("content-encoding".to_owned(), "gzip".to_owned()),
                ("content-length".to_owned(), "42".to_owned()),
                ("x-trace".to_owned(), "abc".to_owned()),
            ],
            true,
        );

        assert_eq!(
            headers,
            vec![
                ("content-type".to_owned(), "text/plain".to_owned()),
                ("x-trace".to_owned(), "abc".to_owned()),
            ],
        );
    }
}
