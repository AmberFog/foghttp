use crate::core::metrics::{Metrics, OriginMetrics};
use crate::messages::CONNECTION_ACQUIRE_TIMEOUT;
use std::collections::HashMap;
use std::error::Error;
use std::fmt::{Display, Formatter};
use std::future::Future;
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use std::time::{Duration, Instant};
use tokio::sync::{OwnedSemaphorePermit, Semaphore, TryAcquireError};

type BoxError = Box<dyn Error + Send + Sync>;

const ORIGIN_GATE_CLEANUP_THRESHOLD: usize = 1024;

tokio::task_local! {
    static CONNECTION_LIMIT_CONTEXT: ConnectionLimitContext;
}

#[derive(Clone)]
pub(crate) struct ConnectionLimitContext {
    timeout: Duration,
    timeout_secs: f64,
    origin: String,
    redirect_hop: usize,
    record_timeout: bool,
}

#[derive(Debug)]
pub(crate) struct ConnectionAcquireTimeout {
    elapsed: f64,
    timeout: f64,
    origin: String,
    redirect_hop: usize,
}

#[derive(Clone)]
pub(crate) struct ConnectionGate {
    global: Option<Arc<Semaphore>>,
    origin_gates: Option<OriginConnectionGates>,
}

#[derive(Default)]
pub(crate) struct ConnectionPermit {
    _global: Option<OwnedSemaphorePermit>,
    _origin: Option<OwnedSemaphorePermit>,
}

#[derive(Clone)]
struct OriginConnectionGates {
    max_connections_per_host: usize,
    gates: Arc<Mutex<HashMap<String, Arc<Semaphore>>>>,
}

struct ConnectionAcquireTelemetry {
    metrics: Arc<Metrics>,
    origin_metrics: Option<Arc<OriginMetrics>>,
    started: Instant,
    waited: bool,
}

impl ConnectionLimitContext {
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
            record_timeout: true,
        }
    }

    fn fallback(origin: Option<&str>) -> Self {
        Self {
            timeout: Duration::ZERO,
            timeout_secs: 0.0,
            origin: origin.unwrap_or_default().to_owned(),
            redirect_hop: 0,
            record_timeout: false,
        }
    }

    fn remaining(&self, started: Instant) -> Duration {
        self.timeout.saturating_sub(started.elapsed())
    }

    fn timeout_error(&self, started: Instant) -> ConnectionAcquireTimeout {
        ConnectionAcquireTimeout {
            elapsed: started.elapsed().as_secs_f64(),
            timeout: self.timeout_secs,
            origin: self.origin.clone(),
            redirect_hop: self.redirect_hop,
        }
    }
}

impl ConnectionAcquireTimeout {
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

impl Display for ConnectionAcquireTimeout {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(CONNECTION_ACQUIRE_TIMEOUT)
    }
}

impl Error for ConnectionAcquireTimeout {}

impl ConnectionGate {
    pub(crate) fn new(
        max_connections: Option<usize>,
        max_connections_per_host: Option<usize>,
    ) -> Self {
        Self {
            global: max_connections.map(|limit| Arc::new(Semaphore::new(limit))),
            origin_gates: max_connections_per_host.map(OriginConnectionGates::new),
        }
    }

    pub(crate) async fn acquire(
        &self,
        origin: Option<&str>,
        metrics: Arc<Metrics>,
        origin_metrics: Option<Arc<OriginMetrics>>,
    ) -> Result<ConnectionPermit, BoxError> {
        let context = current_connection_limit_context()
            .unwrap_or_else(|| ConnectionLimitContext::fallback(origin));
        let started = Instant::now();
        let mut telemetry = ConnectionAcquireTelemetry::start(metrics, origin_metrics);
        let origin_gate = origin.and_then(|origin| {
            self.origin_gates
                .as_ref()
                .map(|origin_gates| origin_gates.semaphore(origin))
        });

        let origin = match origin_gate {
            Some(semaphore) => Some(
                acquire_permit(Arc::clone(&semaphore), &context, started, &mut telemetry).await?,
            ),
            None => None,
        };
        let global = match &self.global {
            Some(semaphore) => Some(
                acquire_permit(Arc::clone(semaphore), &context, started, &mut telemetry).await?,
            ),
            None => None,
        };

        telemetry.finish_success();
        Ok(ConnectionPermit {
            _global: global,
            _origin: origin,
        })
    }
}

impl OriginConnectionGates {
    fn new(max_connections_per_host: usize) -> Self {
        Self {
            max_connections_per_host,
            gates: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    fn semaphore(&self, origin: &str) -> Arc<Semaphore> {
        let mut gates = self.lock_gates();
        if let Some(semaphore) = gates.get(origin) {
            return Arc::clone(semaphore);
        }

        if gates.len() >= ORIGIN_GATE_CLEANUP_THRESHOLD {
            gates.retain(|_origin, semaphore| {
                Arc::strong_count(semaphore) > 1
                    || semaphore.available_permits() < self.max_connections_per_host
            });
        }

        let semaphore = Arc::new(Semaphore::new(self.max_connections_per_host));
        gates.insert(origin.to_owned(), Arc::clone(&semaphore));
        semaphore
    }

    fn lock_gates(&self) -> MutexGuard<'_, HashMap<String, Arc<Semaphore>>> {
        self.gates.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

impl ConnectionAcquireTelemetry {
    fn start(metrics: Arc<Metrics>, origin_metrics: Option<Arc<OriginMetrics>>) -> Self {
        metrics.connection_acquire_started();
        if let Some(origin_metrics) = &origin_metrics {
            origin_metrics.connection_acquire_started();
        }

        Self {
            metrics,
            origin_metrics,
            started: Instant::now(),
            waited: false,
        }
    }

    fn mark_waited(&mut self) {
        if self.waited {
            return;
        }

        self.waited = true;
        self.metrics.connection_acquire_waited();
        if let Some(origin_metrics) = &self.origin_metrics {
            origin_metrics.connection_acquire_waited();
        }
    }

    fn finish_success(&self) {
        if self.waited {
            let elapsed = self.started.elapsed();
            self.metrics.connection_acquire_wait_finished(elapsed);
            if let Some(origin_metrics) = &self.origin_metrics {
                origin_metrics.connection_acquire_wait_finished(elapsed);
            }
            return;
        }

        self.metrics.connection_acquire_finished_immediately();
        if let Some(origin_metrics) = &self.origin_metrics {
            origin_metrics.connection_acquire_finished_immediately();
        }
    }

    fn finish_timeout(&self) {
        self.metrics.connection_acquire_timeout();
        if let Some(origin_metrics) = &self.origin_metrics {
            origin_metrics.connection_acquire_timeout();
        }
    }
}

async fn acquire_permit(
    semaphore: Arc<Semaphore>,
    context: &ConnectionLimitContext,
    started: Instant,
    telemetry: &mut ConnectionAcquireTelemetry,
) -> Result<OwnedSemaphorePermit, BoxError> {
    match Arc::clone(&semaphore).try_acquire_owned() {
        Ok(permit) => return Ok(permit),
        Err(TryAcquireError::Closed) => return Err("connection limiter is closed".into()),
        Err(TryAcquireError::NoPermits) => {}
    }

    telemetry.mark_waited();
    let result = tokio::time::timeout(context.remaining(started), semaphore.acquire_owned()).await;
    match result {
        Ok(Ok(permit)) => Ok(permit),
        Ok(Err(_closed)) => Err("connection limiter is closed".into()),
        Err(_elapsed) => {
            if context.record_timeout {
                telemetry.finish_timeout();
            }
            Err(context.timeout_error(started).into())
        }
    }
}

pub(crate) async fn with_connection_limit_timeout<F>(
    context: Option<ConnectionLimitContext>,
    future: F,
) -> F::Output
where
    F: Future,
{
    match context {
        Some(context) => CONNECTION_LIMIT_CONTEXT.scope(context, future).await,
        None => future.await,
    }
}

pub(crate) fn current_connection_limit_context() -> Option<ConnectionLimitContext> {
    CONNECTION_LIMIT_CONTEXT.try_with(Clone::clone).ok()
}

pub(crate) fn connection_acquire_timeout_from_error<'a>(
    error: &'a (dyn Error + 'static),
) -> Option<&'a ConnectionAcquireTimeout> {
    let mut source = Some(error);
    while let Some(current) = source {
        if let Some(timeout) = current.downcast_ref::<ConnectionAcquireTimeout>() {
            return Some(timeout);
        }
        source = current.source();
    }
    None
}
