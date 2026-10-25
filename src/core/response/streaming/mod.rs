//! Strict, demand-driven content decoding. Network and reservation ownership
//! remain with the caller; each step invokes at most one codec API once.

mod error;

pub use error::StreamDecodeError;

use super::codec::{Codec, CodecStatus, Coding};
use bytes::{Buf, Bytes};
use hyper::header::CONTENT_ENCODING;
use hyper::HeaderMap;

const INPUT_SIZE: usize = 8 * 1024;
const OUTPUT_SIZE: usize = 64 * 1024;
const MAX_LAYERS: usize = 4;
const INFLATE_RESERVATION: usize = 1024 * 1024;
const BROTLI_RESERVATION: usize = 32 * 1024 * 1024;

impl Coding {
    fn reservation(self) -> usize {
        match self {
            Self::Gzip | Self::Deflate => INFLATE_RESERVATION,
            Self::Brotli => BROTLI_RESERVATION,
        }
    }
}

#[derive(Debug)]
pub struct StreamingDecodePlan {
    codings: Vec<Coding>,
}

impl StreamingDecodePlan {
    pub fn from_headers(headers: &HeaderMap) -> Result<Self, StreamDecodeError> {
        let mut codings = Vec::new();
        for value in &headers.get_all(CONTENT_ENCODING) {
            let value = value
                .to_str()
                .map_err(|_| StreamDecodeError::InvalidContentEncoding)?;
            for item in value.split(',') {
                let item = item.trim_matches([' ', '\t']);
                if item.is_empty() || item.eq_ignore_ascii_case("identity") {
                    continue;
                }
                if !item
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || b"!#$%&'*+-.^_`|~".contains(&byte))
                {
                    return Err(StreamDecodeError::InvalidContentEncoding);
                }
                let coding =
                    if item.eq_ignore_ascii_case("gzip") || item.eq_ignore_ascii_case("x-gzip") {
                        Coding::Gzip
                    } else if item.eq_ignore_ascii_case("deflate") {
                        Coding::Deflate
                    } else if item.eq_ignore_ascii_case("br") {
                        Coding::Brotli
                    } else {
                        return Err(StreamDecodeError::UnsupportedCoding);
                    };
                if codings.len() == MAX_LAYERS {
                    return Err(StreamDecodeError::TooManyLayers);
                }
                codings.push(coding);
            }
        }
        codings.reverse();
        Ok(Self { codings })
    }

    pub fn is_encoded(&self) -> bool {
        !self.codings.is_empty()
    }

    /// Admission accounting, not eager allocation or RSS. Qualification and
    /// dependency-version guards live in the separate allocation tests.
    pub fn reservation_bytes(&self) -> usize {
        self.codings
            .iter()
            .copied()
            .map(Coding::reservation)
            .sum::<usize>()
            + (self.codings.len() + 2) * OUTPUT_SIZE
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StepStatus {
    NeedsInput,
    Progress,
    Finished,
}

#[derive(Debug)]
pub struct Step {
    pub consumed: usize,
    pub output: Option<Bytes>,
    pub status: StepStatus,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum LayerState {
    NeedsInput,
    Ready,
    Ended,
    Finished,
}

struct Layer {
    coding: Coding,
    codec: Codec,
    input: Bytes,
    produced: usize,
    state: LayerState,
}

pub struct StreamingDecoder {
    layers: Vec<Layer>,
    scratch: Box<[u8]>,
    max_decoded_bytes: Option<usize>,
    encoded_bytes: usize,
    identity_bytes: usize,
    finished: bool,
    failure: Option<StreamDecodeError>,
}

impl StreamingDecoder {
    /// The caller must acquire the plan's reservation before construction.
    pub fn new(plan: StreamingDecodePlan, max_decoded_bytes: Option<usize>) -> Self {
        Self {
            layers: plan
                .codings
                .into_iter()
                .map(|coding| Layer {
                    coding,
                    codec: Codec::new(coding, OUTPUT_SIZE),
                    input: Bytes::new(),
                    produced: 0,
                    state: LayerState::NeedsInput,
                })
                .collect(),
            scratch: vec![0; OUTPUT_SIZE].into_boxed_slice(),
            max_decoded_bytes,
            encoded_bytes: 0,
            identity_bytes: 0,
            finished: false,
            failure: None,
        }
    }

    /// Keep and resubmit `input[consumed..]`. `real_eof` means no input follows
    /// this slice, not that the slice is empty. `Progress` requires a cancellation
    /// checkpoint before another step. `Finished` never accompanies output.
    pub fn step(&mut self, input: &[u8], real_eof: bool) -> Result<Step, StreamDecodeError> {
        if let Some(error) = &self.failure {
            return Err(error.clone());
        }
        let result = self.advance(input, real_eof);
        if let Err(error) = &result {
            self.failure = Some(error.clone());
        }
        result
    }

    fn advance(&mut self, input: &[u8], real_eof: bool) -> Result<Step, StreamDecodeError> {
        if self.finished {
            if !input.is_empty() {
                return Err(StreamDecodeError::decode(
                    "identity",
                    0,
                    "input after completion",
                ));
            }
            return Ok(Step {
                consumed: 0,
                output: None,
                status: StepStatus::Finished,
            });
        }
        if self.layers.is_empty() {
            return self.identity(input, real_eof);
        }
        // Drain downstream first: a stage never overwrites an occupied slot.
        for index in (0..self.layers.len()).rev() {
            let upstream_eof = if index == 0 {
                real_eof
            } else {
                self.layers[index - 1].state == LayerState::Finished
            };
            let layer = &mut self.layers[index];
            let available = if index == 0 { input } else { &layer.input };
            match layer.state {
                LayerState::Finished => continue,
                LayerState::Ended => {
                    if !available.is_empty() {
                        return Err(StreamDecodeError::decode(
                            layer.coding.name(),
                            index,
                            "trailing data",
                        ));
                    }
                    if upstream_eof {
                        layer.state = LayerState::Finished;
                    }
                    continue;
                }
                LayerState::NeedsInput if available.is_empty() && !upstream_eof => continue,
                LayerState::Ready | LayerState::NeedsInput => {}
            }
            // A downstream stage can end early; allow its upstream to produce
            // one slot so the next step can reject any trailing representation.
            if index + 1 < self.layers.len() && !self.layers[index + 1].input.is_empty() {
                continue;
            }
            return self.run_layer(index, input, upstream_eof);
        }
        self.finished = self
            .layers
            .iter()
            .all(|layer| layer.state == LayerState::Finished);
        Ok(Step {
            consumed: 0,
            output: None,
            status: if self.finished {
                StepStatus::Finished
            } else if real_eof {
                StepStatus::Progress
            } else {
                StepStatus::NeedsInput
            },
        })
    }

    fn run_layer(
        &mut self,
        index: usize,
        input: &[u8],
        upstream_eof: bool,
    ) -> Result<Step, StreamDecodeError> {
        let layer = &mut self.layers[index];
        let available = if index == 0 { input } else { &layer.input };
        let offered = available.len().min(INPUT_SIZE);
        let eof = upstream_eof && offered == available.len();
        let capacity = self.max_decoded_bytes.map_or(OUTPUT_SIZE, |limit| {
            limit
                .saturating_sub(layer.produced)
                .saturating_add(1)
                .min(OUTPUT_SIZE)
        });
        let result = layer
            .codec
            .step(&available[..offered], eof, &mut self.scratch[..capacity])
            .map_err(|source| StreamDecodeError::Decode {
                coding: layer.coding.name(),
                layer: index,
                source: source.into(),
            })?;
        layer.produced = checked_output(
            layer.produced,
            result.produced,
            self.max_decoded_bytes,
            layer.coding.name(),
            index,
        )?;
        let consumed = if index == 0 {
            result.consumed
        } else {
            layer.input.advance(result.consumed);
            0
        };
        self.encoded_bytes = self
            .encoded_bytes
            .checked_add(consumed)
            .ok_or(StreamDecodeError::CounterOverflow)?;
        layer.state = match result.status {
            CodecStatus::NeedsInput => LayerState::NeedsInput,
            CodecStatus::Progress => LayerState::Ready,
            CodecStatus::Ended => LayerState::Ended,
        };
        let output = (result.produced != 0)
            .then(|| Bytes::copy_from_slice(&self.scratch[..result.produced]));
        let output = if index + 1 < self.layers.len() {
            if let Some(bytes) = output {
                self.layers[index + 1].input = bytes;
            }
            None
        } else {
            output
        };
        Ok(Step {
            consumed,
            output,
            status: StepStatus::Progress,
        })
    }

    fn identity(&mut self, input: &[u8], real_eof: bool) -> Result<Step, StreamDecodeError> {
        let consumed = input.len().min(INPUT_SIZE);
        self.identity_bytes = checked_output(
            self.identity_bytes,
            consumed,
            self.max_decoded_bytes,
            "identity",
            0,
        )?;
        self.encoded_bytes = self
            .encoded_bytes
            .checked_add(consumed)
            .ok_or(StreamDecodeError::CounterOverflow)?;
        self.finished = consumed == 0 && real_eof;
        Ok(Step {
            consumed,
            output: (consumed != 0).then(|| Bytes::copy_from_slice(&input[..consumed])),
            status: if self.finished {
                StepStatus::Finished
            } else if consumed == 0 {
                StepStatus::NeedsInput
            } else {
                StepStatus::Progress
            },
        })
    }
}

fn checked_output(
    current: usize,
    produced: usize,
    limit: Option<usize>,
    coding: &'static str,
    layer: usize,
) -> Result<usize, StreamDecodeError> {
    let total = current
        .checked_add(produced)
        .ok_or(StreamDecodeError::CounterOverflow)?;
    if let Some(limit) = limit {
        if total > limit {
            return Err(StreamDecodeError::TooLarge {
                coding,
                layer,
                limit,
            });
        }
    }
    Ok(total)
}

#[cfg(test)]
mod allocation_tests;

#[cfg(test)]
mod tests;
