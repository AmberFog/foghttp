use super::connection_limit::{current_connection_limit_context, with_connection_limit_timeout};
use crate::core::telemetry::{current_request_telemetry, with_request_telemetry};
use crate::messages::REQUEST_BODY_WRITE_TIMEOUT;
use std::error::Error;
use std::fmt::{Display, Formatter};
use std::future::Future;
use std::io;
use std::time::{Duration, Instant};

#[derive(Clone)]
pub(crate) struct RequestWriteTimeoutContext {
    timeout: Duration,
    timeout_secs: f64,
    origin: String,
    redirect_hop: usize,
}

#[derive(Clone, Debug)]
pub(crate) struct RequestWriteTimeout {
    elapsed: f64,
    timeout: f64,
    origin: String,
    redirect_hop: usize,
}

#[derive(Clone, Copy)]
pub(crate) struct RequestTaskContextExecutor;

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

impl<Fut> hyper::rt::Executor<Fut> for RequestTaskContextExecutor
where
    Fut: Future + Send + 'static,
    Fut::Output: Send + 'static,
{
    fn execute(&self, future: Fut) {
        let connection_context = current_connection_limit_context();
        let telemetry = current_request_telemetry();
        tokio::spawn(async move {
            with_request_telemetry(telemetry, async {
                with_connection_limit_timeout(connection_context, future).await;
            })
            .await;
        });
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
mod tests;
