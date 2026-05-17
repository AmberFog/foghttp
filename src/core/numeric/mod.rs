use std::time::{Duration, Instant};

pub const MAX_NUMERIC_OPTION: usize = i32::MAX as usize;

const MAX_DURATION_SECONDS: f64 = 2_147_483_647.0;

pub fn validate_usize_option(name: &str, value: usize) -> Result<usize, String> {
    if value <= MAX_NUMERIC_OPTION {
        return Ok(value);
    }

    Err(integer_error(name))
}

pub fn validate_optional_usize_option(
    name: &str,
    value: Option<usize>,
) -> Result<Option<usize>, String> {
    value
        .map(|value| validate_usize_option(name, value))
        .transpose()
}

pub fn duration_from_secs(name: &str, seconds: f64) -> Result<Duration, String> {
    if seconds.is_finite() && (0.0..=MAX_DURATION_SECONDS).contains(&seconds) {
        return Ok(Duration::from_secs_f64(seconds));
    }

    Err(seconds_error(name))
}

pub fn remaining_duration(name: &str, seconds: f64, started: Instant) -> Result<Duration, String> {
    duration_from_secs(name, seconds).map(|duration| duration.saturating_sub(started.elapsed()))
}

fn integer_error(name: &str) -> String {
    format!("{name} must be an integer between 0 and {MAX_NUMERIC_OPTION}")
}

fn seconds_error(name: &str) -> String {
    format!("{name} must be a finite number between 0 and {MAX_NUMERIC_OPTION}")
}

#[cfg(test)]
mod tests;
