use super::{request_write_timeout_from_error, RequestWriteTimeout, REQUEST_BODY_WRITE_TIMEOUT};
use std::io::{Error, ErrorKind};

const ELAPSED_SECS: f64 = 0.25;
const ORIGIN: &str = "https://api.example.com";
const TIMEOUT_SECS: f64 = 0.2;

#[test]
fn request_write_timeout_from_error_finds_io_error_source() {
    let error = Error::new(
        ErrorKind::TimedOut,
        RequestWriteTimeout {
            elapsed: ELAPSED_SECS,
            timeout: TIMEOUT_SECS,
            origin: ORIGIN.to_owned(),
            redirect_hop: 1,
        },
    );

    let timeout = request_write_timeout_from_error(&error)
        .expect("expected request write timeout in error source chain");

    assert_eq!(timeout.to_string(), REQUEST_BODY_WRITE_TIMEOUT);
    assert_float_eq(timeout.elapsed(), ELAPSED_SECS);
    assert_float_eq(timeout.timeout(), TIMEOUT_SECS);
    assert_eq!(timeout.origin(), ORIGIN);
    assert_eq!(timeout.redirect_hop(), 1);
}

fn assert_float_eq(actual: f64, expected: f64) {
    assert!((actual - expected).abs() < f64::EPSILON);
}
