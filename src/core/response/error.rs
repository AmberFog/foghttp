use crate::messages::{buffered_response_body_budget_exceeded, response_body_too_large};
use std::error::Error;
use std::fmt::{Display, Formatter};
use std::io;

#[derive(Debug)]
pub enum ResponseBodyError {
    TooLarge {
        limit: usize,
    },
    BudgetExceeded {
        limit: usize,
    },
    CounterOverflow,
    ReservationOverflow,
    ReservationUnderflow,
    DecodeReservationOverflow,
    Decode {
        coding: &'static str,
        source: io::Error,
    },
}

impl Display for ResponseBodyError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::TooLarge { limit } => formatter.write_str(&response_body_too_large(*limit)),
            Self::BudgetExceeded { limit } => {
                formatter.write_str(&buffered_response_body_budget_exceeded(*limit))
            }
            Self::CounterOverflow => formatter.write_str("buffered response byte counter overflow"),
            Self::ReservationOverflow => {
                formatter.write_str("buffered response byte reservation overflow")
            }
            Self::ReservationUnderflow => {
                formatter.write_str("buffered response byte reservation underflow")
            }
            Self::DecodeReservationOverflow => {
                formatter.write_str("decoded response byte reservation overflow")
            }
            Self::Decode { coding, source } => {
                write!(
                    formatter,
                    "failed to decode {coding} response body: {source}"
                )
            }
        }
    }
}

impl Error for ResponseBodyError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Decode { source, .. } => Some(source),
            _ => None,
        }
    }
}
