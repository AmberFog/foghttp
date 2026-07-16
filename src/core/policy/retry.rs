use super::request::{PolicyRequest, ResponseHead};
use crate::core::headers::HeaderPairs;
use crate::core::numeric::{duration_from_secs, validate_usize_option, MAX_NUMERIC_OPTION};
use hyper::Method;
use std::collections::HashSet;
use std::time::{Duration, SystemTime};

const MAX_RETRY_DELAY: Duration = Duration::from_secs(MAX_NUMERIC_OPTION as u64);
const RETRY_AFTER: &str = "retry-after";

#[derive(Clone, Debug)]
pub(crate) struct RetryPolicy {
    retries: usize,
    backoff: Duration,
    jitter: Duration,
    statuses: HashSet<u16>,
    methods: HashSet<String>,
    network_errors: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum RetryDecision {
    Retry { delay: Duration },
    Stop { reason: RetryStopReason },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum RetryStopReason {
    MethodNotAllowed,
    NonReplayableBody,
    RetriesExhausted,
}

impl RetryPolicy {
    pub(crate) fn new(
        retries: usize,
        backoff: f64,
        jitter: f64,
        statuses: Vec<u16>,
        methods: Vec<String>,
        network_errors: bool,
    ) -> Result<Self, String> {
        let retries = validate_usize_option("RetryPolicy.retries", retries)?;
        let backoff = duration_from_secs("RetryPolicy.backoff", backoff)?;
        let jitter = duration_from_secs("RetryPolicy.jitter", jitter)?;
        let statuses = validate_statuses(statuses)?;
        let methods = validate_methods(methods)?;
        Ok(Self {
            retries,
            backoff,
            jitter,
            statuses,
            methods,
            network_errors,
        })
    }

    pub(crate) fn on_response(
        &self,
        request: PolicyRequest<'_>,
        response: ResponseHead<'_>,
        completed_retries: usize,
        jitter_sample: f64,
        now: SystemTime,
    ) -> Option<RetryDecision> {
        self.statuses.contains(&response.status_code()).then(|| {
            self.decision(
                request,
                completed_retries,
                jitter_sample,
                retry_after(response.headers(), now),
            )
        })
    }

    pub(crate) fn on_network_error(
        &self,
        request: PolicyRequest<'_>,
        completed_retries: usize,
        jitter_sample: f64,
    ) -> Option<RetryDecision> {
        self.network_errors
            .then(|| self.decision(request, completed_retries, jitter_sample, None))
    }

    fn decision(
        &self,
        request: PolicyRequest<'_>,
        completed_retries: usize,
        jitter_sample: f64,
        minimum_delay: Option<Duration>,
    ) -> RetryDecision {
        if !request.body().can_replay() {
            return RetryDecision::Stop {
                reason: RetryStopReason::NonReplayableBody,
            };
        }
        if !self.methods.contains(request.method()) {
            return RetryDecision::Stop {
                reason: RetryStopReason::MethodNotAllowed,
            };
        }
        if completed_retries >= self.retries {
            return RetryDecision::Stop {
                reason: RetryStopReason::RetriesExhausted,
            };
        }

        let configured_delay = self.delay(completed_retries, jitter_sample);
        let delay = minimum_delay
            .map_or(configured_delay, |delay| delay.max(configured_delay))
            .min(MAX_RETRY_DELAY);
        RetryDecision::Retry { delay }
    }

    fn delay(&self, completed_retries: usize, jitter_sample: f64) -> Duration {
        let exponent = i32::try_from(completed_retries.min(i32::MAX as usize))
            .expect("retry exponent is capped at i32::MAX");
        let exponential = self.backoff.as_secs_f64() * 2.0_f64.powi(exponent);
        let jitter = self.jitter.as_secs_f64() * jitter_sample.clamp(0.0, 1.0);
        Duration::from_secs_f64((exponential + jitter).min(MAX_RETRY_DELAY.as_secs_f64()))
    }
}

fn validate_statuses(statuses: Vec<u16>) -> Result<HashSet<u16>, String> {
    if statuses.iter().all(|status| (100..=599).contains(status)) {
        return Ok(statuses.into_iter().collect());
    }
    Err("RetryConditions.statuses must contain values between 100 and 599".to_owned())
}

fn validate_methods(methods: Vec<String>) -> Result<HashSet<String>, String> {
    methods
        .into_iter()
        .map(|method| {
            Method::from_bytes(method.as_bytes())
                .map(|method| method.as_str().to_ascii_uppercase())
                .map_err(|_| "RetryPolicy.methods must contain valid HTTP method tokens".to_owned())
        })
        .collect()
}

fn retry_after(headers: &HeaderPairs, now: SystemTime) -> Option<Duration> {
    headers
        .iter()
        .filter(|(name, _value)| name.eq_ignore_ascii_case(RETRY_AFTER))
        .find_map(|(_name, value)| parse_retry_after(value.trim(), now))
}

fn parse_retry_after(value: &str, now: SystemTime) -> Option<Duration> {
    if let Ok(seconds) = value.parse::<u64>() {
        return Some(Duration::from_secs(seconds));
    }
    httpdate::parse_http_date(value)
        .ok()
        .map(|deadline| deadline.duration_since(now).unwrap_or(Duration::ZERO))
}

#[cfg(test)]
mod tests;
