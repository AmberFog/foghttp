use crate::messages::REQUEST_BODY_WRITE_TIMEOUT;
use std::error::Error;
use std::fmt::{Display, Formatter};
use std::future::Future;
use std::io;
use std::time::{Duration, Instant};

tokio::task_local! {
    static REQUEST_WRITE_TIMEOUT: RequestWriteTimeoutContext;
}

#[derive(Clone)]
pub(crate) struct RequestWriteTimeoutContext {
    timeout: Duration,
    timeout_secs: f64,
    origin: String,
    redirect_hop: usize,
}

#[derive(Debug)]
pub(crate) struct RequestWriteTimeout {
    elapsed: f64,
    timeout: f64,
    origin: String,
    redirect_hop: usize,
}

#[derive(Clone, Copy)]
pub(crate) struct RequestWriteTimeoutExecutor;

impl RequestWriteTimeoutContext {
    pub(crate) fn new(
        timeout: Duration,
        timeout_secs: f64,
        origin: String,
        redirect_hop: usize,
    ) -> Self {
        Self {
            timeout,
            timeout_secs,
            origin,
            redirect_hop,
        }
    }

    pub(crate) fn timeout(&self) -> Duration {
        self.timeout
    }

    pub(crate) fn timeout_error(&self, started: Instant) -> RequestWriteTimeout {
        RequestWriteTimeout {
            elapsed: started.elapsed().as_secs_f64(),
            timeout: self.timeout_secs,
            origin: self.origin.clone(),
            redirect_hop: self.redirect_hop,
        }
    }
}

impl RequestWriteTimeout {
    pub(crate) fn elapsed(&self) -> f64 {
        self.elapsed
    }

    pub(crate) fn timeout(&self) -> f64 {
        self.timeout
    }

    pub(crate) fn origin(&self) -> &str {
        &self.origin
    }

    pub(crate) fn redirect_hop(&self) -> usize {
        self.redirect_hop
    }
}

impl Display for RequestWriteTimeout {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(REQUEST_BODY_WRITE_TIMEOUT)
    }
}

impl Error for RequestWriteTimeout {}

pub(crate) async fn with_request_write_timeout<F>(
    context: Option<RequestWriteTimeoutContext>,
    future: F,
) -> F::Output
where
    F: Future,
{
    match context {
        Some(context) => REQUEST_WRITE_TIMEOUT.scope(context, future).await,
        None => future.await,
    }
}

pub(crate) fn current_request_write_timeout() -> Option<RequestWriteTimeoutContext> {
    REQUEST_WRITE_TIMEOUT.try_with(Clone::clone).ok()
}

impl<Fut> hyper::rt::Executor<Fut> for RequestWriteTimeoutExecutor
where
    Fut: Future + Send + 'static,
    Fut::Output: Send + 'static,
{
    fn execute(&self, future: Fut) {
        match current_request_write_timeout() {
            Some(context) => {
                tokio::spawn(async move {
                    REQUEST_WRITE_TIMEOUT.scope(context, future).await;
                });
            }
            None => {
                tokio::spawn(future);
            }
        }
    }
}

pub(crate) fn request_write_timeout_from_error<'a>(
    error: &'a (dyn Error + 'static),
) -> Option<&'a RequestWriteTimeout> {
    let mut source = Some(error);
    while let Some(current) = source {
        if let Some(timeout) = current.downcast_ref::<RequestWriteTimeout>() {
            return Some(timeout);
        }
        if let Some(io_error) = current.downcast_ref::<io::Error>() {
            if let Some(timeout) = io_error
                .get_ref()
                .and_then(|error| request_write_timeout_from_error(error))
            {
                return Some(timeout);
            }
        }
        source = current.source();
    }
    None
}

#[cfg(test)]
mod tests {
    use super::{
        request_write_timeout_from_error, RequestWriteTimeout, REQUEST_BODY_WRITE_TIMEOUT,
    };
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
}
