#[cfg(test)]
mod tests;

use crate::core::metrics::{Metrics, OriginMetrics, ResponseBodyLifecycleOutcome};
use crate::core::url::HttpUrl;
use hyper::rt::{Read, ReadBufCursor, Write};
use hyper::Uri;
use hyper_util::client::legacy::connect::{Connected, Connection};
use std::future::Future;
use std::io::{Error, IoSlice};
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::task::{Context, Poll};
use tower_service::Service;

#[derive(Clone)]
pub(crate) struct InstrumentedConnector<C> {
    inner: C,
    metrics: Arc<Metrics>,
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
}

struct ConnectionTelemetryInner {
    metrics: Arc<Metrics>,
    origin_metrics: Option<Arc<OriginMetrics>>,
    observed_uses: AtomicUsize,
    idle: AtomicBool,
    closed: AtomicBool,
    aborted: AtomicBool,
}

impl<C> InstrumentedConnector<C> {
    pub(crate) fn new(inner: C, metrics: Arc<Metrics>) -> Self {
        Self { inner, metrics }
    }
}

impl<C> Service<Uri> for InstrumentedConnector<C>
where
    C: Service<Uri>,
    C::Response: Read + Write + Connection + Unpin + Send + 'static,
    C::Future: Send + 'static,
{
    type Response = InstrumentedConnection<C::Response>;
    type Error = C::Error;
    type Future = Pin<Box<dyn Future<Output = Result<Self::Response, Self::Error>> + Send>>;

    fn poll_ready(&mut self, context: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.inner.poll_ready(context)
    }

    fn call(&mut self, uri: Uri) -> Self::Future {
        let metrics = Arc::clone(&self.metrics);
        let origin_metrics = origin_from_uri(&uri).map(|origin| metrics.origin_metrics(&origin));
        let future = self.inner.call(uri);

        Box::pin(async move {
            match future.await {
                Ok(inner) => {
                    let telemetry = ConnectionTelemetry::new(metrics, origin_metrics);
                    Ok(InstrumentedConnection { inner, telemetry })
                }
                Err(error) => {
                    metrics.connection_open_failed();
                    if let Some(origin_metrics) = origin_metrics {
                        origin_metrics.connection_open_failed();
                    }
                    Err(error)
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
        Pin::new(&mut self.get_mut().inner).poll_write(context, buffer)
    }

    fn poll_flush(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Result<(), Error>> {
        Pin::new(&mut self.get_mut().inner).poll_flush(context)
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
        Pin::new(&mut self.get_mut().inner).poll_write_vectored(context, buffers)
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
