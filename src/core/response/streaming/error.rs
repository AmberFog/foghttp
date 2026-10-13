use std::error::Error;
use std::fmt::{Display, Formatter};
use std::io;
use std::sync::Arc;

#[derive(Clone, Debug)]
pub enum StreamDecodeError {
    InvalidContentEncoding,
    UnsupportedCoding,
    TooManyLayers,
    TooLarge {
        coding: &'static str,
        layer: usize,
        limit: usize,
    },
    CounterOverflow,
    Decode {
        coding: &'static str,
        layer: usize,
        source: Arc<io::Error>,
    },
}

impl StreamDecodeError {
    pub(super) fn decode(coding: &'static str, layer: usize, reason: &'static str) -> Self {
        Self::Decode {
            coding,
            layer,
            source: Arc::new(io::Error::new(io::ErrorKind::InvalidData, reason)),
        }
    }
}

impl Display for StreamDecodeError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidContentEncoding => {
                formatter.write_str("invalid streaming content-encoding syntax")
            }
            Self::UnsupportedCoding => formatter.write_str("unsupported streaming content coding"),
            Self::TooManyLayers => {
                formatter.write_str("streaming content coding exceeds four layers")
            }
            Self::TooLarge {
                coding,
                layer,
                limit,
            } => write!(
                formatter,
                "streaming {coding} layer {layer} exceeds decoded byte limit {limit}"
            ),
            Self::CounterOverflow => {
                formatter.write_str("streaming response byte counter overflow")
            }
            Self::Decode {
                coding,
                layer,
                source,
            } => write!(
                formatter,
                "failed to decode streaming {coding} layer {layer}: {source}"
            ),
        }
    }
}

impl Error for StreamDecodeError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Decode { source, .. } => Some(source.as_ref()),
            _ => None,
        }
    }
}
