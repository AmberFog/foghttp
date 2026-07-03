#[cfg(test)]
mod tests;

use super::connection_limit::{ConnectionGate, ConnectionPermit};
use super::write_timeout::{current_request_write_timeout, RequestWriteTimeoutContext};
use crate::core::metrics::{Metrics, OriginMetrics, ResponseBodyLifecycleOutcome};
use crate::core::url::HttpUrl;
use hyper::rt::{Read, ReadBufCursor, Write};
use hyper::Uri;
use hyper_util::client::legacy::connect::{Connected, Connection};
use std::future::Future;
use std::io::{Error, ErrorKind, IoSlice};
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::task::{Context, Poll};
use std::time::Instant;
use tokio::time::Sleep;
use tower_service::Service;

type BoxError = Box<dyn std::error::Error + Send + Sync>;

#[derive(Clone)]
pub(crate) struct InstrumentedConnector<C> {
    inner: C,
    metrics: Arc<Metrics>,
    connection_gate: ConnectionGate,
}

#[derive(Clone)]
pub(crate) struct ConnectionTelemetry {
    inner: Arc<ConnectionTelemetryInner>,
}

pub(crate) struct ConnectionUseGuard {
    telemetry: ConnectionTelemetry,
    finished: bool,
}

pub(crate) struct InstrumentedConnection<T> {
    inner: T,
    telemetry: ConnectionTelemetry,
    write_timeout: WriteTimeoutState,
    _connection_permit: ConnectionPermit,
}

struct ConnectionTelemetryInner {
    metrics: Arc<Metrics>,
    origin_metrics: Option<Arc<OriginMetrics>>,
    observed_uses: AtomicUsize,
    idle: AtomicBool,
    closed: AtomicBool,
    aborted: AtomicBool,
}

#[derive(Default)]
struct WriteTimeoutState {
    pending_since: Option<Instant>,
    sleep: Option<Pin<Box<Sleep>>>,
    context: Option<RequestWriteTimeoutContext>,
}

impl<C> InstrumentedConnector<C> {
    pub(crate) fn new(inner: C, metrics: Arc<Metrics>, connection_gate: ConnectionGate) -> Self {
        Self {
            inner,
            metrics,
            connection_gate,
        }
    }
}

impl<C> Service<Uri> for InstrumentedConnector<C>
where
    C: Service<Uri>,
    C::Response: Read + Write + Connection + Unpin + Send + 'static,
    C::Future: Send + 'static,
    C::Error: Into<BoxError>,
{
    type Response = InstrumentedConnection<C::Response>;
    type Error = BoxError;
    type Future = Pin<Box<dyn Future<Output = Result<Self::Response, Self::Error>> + Send>>;

    fn poll_ready(&mut self, context: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.inner.poll_ready(context).map_err(Into::into)
    }

    fn call(&mut self, uri: Uri) -> Self::Future {
        let metrics = Arc::clone(&self.metrics);
        let connection_gate = self.connection_gate.clone();
        let origin = origin_from_uri(&uri);
        let origin_metrics = origin.as_ref().map(|origin| metrics.origin_metrics(origin));
        let future = self.inner.call(uri);

        Box::pin(async move {
            let connection_permit = connection_gate
                .acquire(
                    origin.as_deref(),
                    Arc::clone(&metrics),
                    origin_metrics.clone(),
                )
                .await?;
            match future.await {
                Ok(inner) => {
                    let telemetry = ConnectionTelemetry::new(metrics, origin_metrics);
                    Ok(InstrumentedConnection {
                        inner,
                        telemetry,
                        write_timeout: WriteTimeoutState::default(),
                        _connection_permit: connection_permit,
                    })
                }
                Err(error) => {
                    metrics.connection_open_failed();
                    if let Some(origin_metrics) = origin_metrics {
                        origin_metrics.connection_open_failed();
                    }
                    Err(error.into())
                }
            }
        })
    }
}

impl ConnectionTelemetry {
    fn new(metrics: Arc<Metrics>, origin_metrics: Option<Arc<OriginMetrics>>) -> Self {
        metrics.connection_opened();
        if let Some(origin_metrics) = &origin_metrics {
            origin_metrics.connection_opened();
        }

        Self {
            inner: Arc::new(ConnectionTelemetryInner {
                metrics,
                origin_metrics,
                observed_uses: AtomicUsize::new(0),
                idle: AtomicBool::new(false),
                closed: AtomicBool::new(false),
                aborted: AtomicBool::new(false),
            }),
        }
    }

    pub(crate) fn response_started(&self) -> ConnectionUseGuard {
        self.leave_idle();
        let previous_uses = self.inner.observed_uses.fetch_add(1, Ordering::Relaxed);
        if previous_uses > 0 {
            self.inner.metrics.connection_reused();
            if let Some(origin_metrics) = &self.inner.origin_metrics {
                origin_metrics.connection_reused();
            }
        }

        ConnectionUseGuard {
            telemetry: self.clone(),
            finished: false,
        }
    }

    fn response_finished(&self, outcome: ResponseBodyLifecycleOutcome) {
        match outcome {
            ResponseBodyLifecycleOutcome::ReuseEligible => self.enter_idle(),
            ResponseBodyLifecycleOutcome::Closed => {}
            ResponseBodyLifecycleOutcome::Aborted => self.abort(),
        }
    }

    fn connection_closed(&self) {
        self.leave_idle();
        if self.inner.closed.swap(true, Ordering::AcqRel) {
            return;
        }

        self.inner.metrics.connection_closed();
        if let Some(origin_metrics) = &self.inner.origin_metrics {
            origin_metrics.connection_closed();
        }
    }

    fn enter_idle(&self) {
        if self.inner.closed.load(Ordering::Acquire) {
            return;
        }
        if self.inner.idle.swap(true, Ordering::AcqRel) {
            return;
        }

        self.inner.metrics.connection_became_idle();
        if let Some(origin_metrics) = &self.inner.origin_metrics {
            origin_metrics.connection_became_idle();
        }
    }

    fn leave_idle(&self) {
        if !self.inner.idle.swap(false, Ordering::AcqRel) {
            return;
        }

        self.inner.metrics.connection_left_idle();
        if let Some(origin_metrics) = &self.inner.origin_metrics {
            origin_metrics.connection_left_idle();
        }
    }

    fn abort(&self) {
        if self.inner.aborted.swap(true, Ordering::AcqRel) {
            return;
        }

        self.inner.metrics.connection_aborted();
        if let Some(origin_metrics) = &self.inner.origin_metrics {
            origin_metrics.connection_aborted();
        }
    }
}

impl WriteTimeoutState {
    fn reset(&mut self) {
        self.pending_since = None;
        self.sleep = None;
        self.context = None;
    }

    fn poll_pending(&mut self, context: &mut Context<'_>) -> Poll<Error> {
        if self.context.is_none() {
            self.context = current_request_write_timeout();
            if self.context.is_none() {
                self.reset();
                return Poll::Pending;
            }
        }
        let timeout_context = self
            .context
            .as_ref()
            .expect("write timeout context is checked before polling timeout");
        let pending_since = *self.pending_since.get_or_insert_with(Instant::now);
        let sleep = self
            .sleep
            .get_or_insert_with(|| Box::pin(tokio::time::sleep(timeout_context.timeout())));

        if sleep.as_mut().poll(context).is_pending() {
            return Poll::Pending;
        }

        let timeout_error = timeout_context.timeout_error(pending_since);
        self.reset();
        Poll::Ready(Error::new(ErrorKind::TimedOut, timeout_error))
    }
}

impl<T> InstrumentedConnection<T> {
    fn poll_pending_write_timeout(&mut self, context: &mut Context<'_>) -> Poll<Error> {
        match self.write_timeout.poll_pending(context) {
            Poll::Ready(error) => {
                self.telemetry.abort();
                Poll::Ready(error)
            }
            Poll::Pending => Poll::Pending,
        }
    }
}

impl ConnectionUseGuard {
    pub(crate) fn finish(mut self, outcome: ResponseBodyLifecycleOutcome) {
        self.telemetry.response_finished(outcome);
        self.finished = true;
    }
}

impl Drop for ConnectionUseGuard {
    fn drop(&mut self) {
        if !self.finished {
            self.telemetry
                .response_finished(ResponseBodyLifecycleOutcome::Aborted);
        }
    }
}

impl<T> Connection for InstrumentedConnection<T>
where
    T: Connection,
{
    fn connected(&self) -> Connected {
        self.inner.connected().extra(self.telemetry.clone())
    }
}

impl<T> Read for InstrumentedConnection<T>
where
    T: Read + Unpin,
{
    fn poll_read(
        self: Pin<&mut Self>,
        context: &mut Context<'_>,
        buffer: ReadBufCursor<'_>,
    ) -> Poll<Result<(), Error>> {
        Pin::new(&mut self.get_mut().inner).poll_read(context, buffer)
    }
}

impl<T> Write for InstrumentedConnection<T>
where
    T: Write + Unpin,
{
    fn poll_write(
        self: Pin<&mut Self>,
        context: &mut Context<'_>,
        buffer: &[u8],
    ) -> Poll<Result<usize, Error>> {
        let connection = self.get_mut();
        match Pin::new(&mut connection.inner).poll_write(context, buffer) {
            Poll::Ready(result) => {
                connection.write_timeout.reset();
                Poll::Ready(result)
            }
            Poll::Pending => match connection.poll_pending_write_timeout(context) {
                Poll::Ready(error) => Poll::Ready(Err(error)),
                Poll::Pending => Poll::Pending,
            },
        }
    }

    fn poll_flush(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Result<(), Error>> {
        let connection = self.get_mut();
        match Pin::new(&mut connection.inner).poll_flush(context) {
            Poll::Ready(result) => {
                connection.write_timeout.reset();
                Poll::Ready(result)
            }
            Poll::Pending => match connection.poll_pending_write_timeout(context) {
                Poll::Ready(error) => Poll::Ready(Err(error)),
                Poll::Pending => Poll::Pending,
            },
        }
    }

    fn poll_shutdown(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Result<(), Error>> {
        Pin::new(&mut self.get_mut().inner).poll_shutdown(context)
    }

    fn is_write_vectored(&self) -> bool {
        self.inner.is_write_vectored()
    }

    fn poll_write_vectored(
        self: Pin<&mut Self>,
        context: &mut Context<'_>,
        buffers: &[IoSlice<'_>],
    ) -> Poll<Result<usize, Error>> {
        let connection = self.get_mut();
        match Pin::new(&mut connection.inner).poll_write_vectored(context, buffers) {
            Poll::Ready(result) => {
                connection.write_timeout.reset();
                Poll::Ready(result)
            }
            Poll::Pending => match connection.poll_pending_write_timeout(context) {
                Poll::Ready(error) => Poll::Ready(Err(error)),
                Poll::Pending => Poll::Pending,
            },
        }
    }
}

impl<T> Drop for InstrumentedConnection<T> {
    fn drop(&mut self) {
        self.telemetry.connection_closed();
    }
}

fn origin_from_uri(uri: &Uri) -> Option<String> {
    HttpUrl::parse(&uri.to_string())
        .ok()
        .map(|url| url.origin())
}
