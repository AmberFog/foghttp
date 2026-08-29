use super::atomic::{duration_as_nanos, saturating_atomic_usize_sub, update_atomic_u64_max};
use super::telemetry::TelemetrySnapshotMetadata;
use super::Metrics;
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, PoisonError, RwLock, RwLockReadGuard, RwLockWriteGuard};
use std::time::Instant;

pub struct ProxyEndpointMetrics {
    endpoint: String,
    started_at: Instant,
    connection_attempts: AtomicUsize,
    connections_opened: AtomicUsize,
    connections_open_failed: AtomicUsize,
    connections_closed: AtomicUsize,
    active_connections: AtomicUsize,
    tunnel_attempts: AtomicUsize,
    tunnels_established: AtomicUsize,
    tunnel_failures: AtomicUsize,
    tunnel_auth_failures: AtomicUsize,
    tunnel_timeouts: AtomicUsize,
    tunnel_early_closes: AtomicUsize,
    active_tunnels: AtomicUsize,
    last_activity_at_ns: AtomicU64,
}

pub struct ProxyEndpointMetricsSnapshot {
    pub endpoint: String,
    pub connection_attempts: usize,
    pub connections_opened: usize,
    pub connections_open_failed: usize,
    pub connections_closed: usize,
    pub active_connections: usize,
    pub tunnel_attempts: usize,
    pub tunnels_established: usize,
    pub tunnel_failures: usize,
    pub tunnel_auth_failures: usize,
    pub tunnel_timeouts: usize,
    pub tunnel_early_closes: usize,
    pub active_tunnels: usize,
    pub last_activity_at_ns: u64,
}

pub struct ProxyDiagnosticsSnapshot {
    pub metadata: TelemetrySnapshotMetadata,
    pub endpoints: Vec<ProxyEndpointMetricsSnapshot>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProxyTunnelFailureKind {
    Authentication,
    Timeout,
    EarlyClose,
    Other,
}

pub struct ProxyConnectionAttempt {
    metrics: Arc<ProxyEndpointMetrics>,
    finished: bool,
}

pub struct ProxyConnectionLease {
    metrics: Arc<ProxyEndpointMetrics>,
    tunnel_active: bool,
}

pub struct ProxyTunnelAttempt {
    metrics: Arc<ProxyEndpointMetrics>,
    finished: bool,
}

pub(super) struct ProxyEndpointMetricsRegistry {
    started_at: Instant,
    endpoints: RwLock<HashMap<String, Arc<ProxyEndpointMetrics>>>,
}

impl Default for ProxyEndpointMetricsRegistry {
    fn default() -> Self {
        Self {
            started_at: Instant::now(),
            endpoints: RwLock::new(HashMap::new()),
        }
    }
}

impl ProxyEndpointMetricsRegistry {
    fn metrics_for(&self, endpoint: &str) -> Arc<ProxyEndpointMetrics> {
        if let Some(metrics) = self.read_endpoints().get(endpoint) {
            return Arc::clone(metrics);
        }

        let mut endpoints = self.write_endpoints();
        if let Some(metrics) = endpoints.get(endpoint) {
            return Arc::clone(metrics);
        }

        let metrics = Arc::new(ProxyEndpointMetrics::new(
            endpoint.to_owned(),
            self.started_at,
        ));
        endpoints.insert(endpoint.to_owned(), Arc::clone(&metrics));
        metrics
    }

    fn snapshots(&self) -> Vec<ProxyEndpointMetricsSnapshot> {
        let endpoints = self.read_endpoints();
        let mut snapshots = endpoints
            .values()
            .map(|metrics| metrics.snapshot())
            .collect::<Vec<_>>();
        snapshots.sort_by(|left, right| left.endpoint.cmp(&right.endpoint));
        snapshots
    }

    fn read_endpoints(&self) -> RwLockReadGuard<'_, HashMap<String, Arc<ProxyEndpointMetrics>>> {
        self.endpoints
            .read()
            .unwrap_or_else(PoisonError::into_inner)
    }

    fn write_endpoints(&self) -> RwLockWriteGuard<'_, HashMap<String, Arc<ProxyEndpointMetrics>>> {
        self.endpoints
            .write()
            .unwrap_or_else(PoisonError::into_inner)
    }
}

impl ProxyEndpointMetrics {
    fn new(endpoint: String, started_at: Instant) -> Self {
        Self {
            endpoint,
            started_at,
            connection_attempts: AtomicUsize::new(0),
            connections_opened: AtomicUsize::new(0),
            connections_open_failed: AtomicUsize::new(0),
            connections_closed: AtomicUsize::new(0),
            active_connections: AtomicUsize::new(0),
            tunnel_attempts: AtomicUsize::new(0),
            tunnels_established: AtomicUsize::new(0),
            tunnel_failures: AtomicUsize::new(0),
            tunnel_auth_failures: AtomicUsize::new(0),
            tunnel_timeouts: AtomicUsize::new(0),
            tunnel_early_closes: AtomicUsize::new(0),
            active_tunnels: AtomicUsize::new(0),
            last_activity_at_ns: AtomicU64::new(0),
        }
    }

    pub fn connection_attempt(self: &Arc<Self>) -> ProxyConnectionAttempt {
        self.connection_attempts.fetch_add(1, Ordering::Relaxed);
        self.touch();
        ProxyConnectionAttempt {
            metrics: Arc::clone(self),
            finished: false,
        }
    }

    pub fn tunnel_attempt(self: &Arc<Self>) -> ProxyTunnelAttempt {
        self.tunnel_attempts.fetch_add(1, Ordering::Relaxed);
        self.touch();
        ProxyTunnelAttempt {
            metrics: Arc::clone(self),
            finished: false,
        }
    }

    fn connection_opened(&self) {
        self.connections_opened.fetch_add(1, Ordering::Relaxed);
        self.active_connections.fetch_add(1, Ordering::Relaxed);
        self.touch();
    }

    fn connection_open_failed(&self) {
        self.connections_open_failed.fetch_add(1, Ordering::Relaxed);
        self.touch();
    }

    fn connection_closed(&self, tunnel_active: bool) {
        if tunnel_active {
            saturating_atomic_usize_sub(&self.active_tunnels, 1);
        }
        saturating_atomic_usize_sub(&self.active_connections, 1);
        self.connections_closed.fetch_add(1, Ordering::Relaxed);
        self.touch();
    }

    fn tunnel_established(&self) {
        self.tunnels_established.fetch_add(1, Ordering::Relaxed);
        self.active_tunnels.fetch_add(1, Ordering::Relaxed);
        self.touch();
    }

    fn tunnel_failed(&self, kind: ProxyTunnelFailureKind) {
        self.tunnel_failures.fetch_add(1, Ordering::Relaxed);
        match kind {
            ProxyTunnelFailureKind::Authentication => {
                self.tunnel_auth_failures.fetch_add(1, Ordering::Relaxed);
            }
            ProxyTunnelFailureKind::Timeout => {
                self.tunnel_timeouts.fetch_add(1, Ordering::Relaxed);
            }
            ProxyTunnelFailureKind::EarlyClose => {
                self.tunnel_early_closes.fetch_add(1, Ordering::Relaxed);
            }
            ProxyTunnelFailureKind::Other => {}
        }
        self.touch();
    }

    fn snapshot(&self) -> ProxyEndpointMetricsSnapshot {
        ProxyEndpointMetricsSnapshot {
            endpoint: self.endpoint.clone(),
            connection_attempts: self.connection_attempts.load(Ordering::Relaxed),
            connections_opened: self.connections_opened.load(Ordering::Relaxed),
            connections_open_failed: self.connections_open_failed.load(Ordering::Relaxed),
            connections_closed: self.connections_closed.load(Ordering::Relaxed),
            active_connections: self.active_connections.load(Ordering::Relaxed),
            tunnel_attempts: self.tunnel_attempts.load(Ordering::Relaxed),
            tunnels_established: self.tunnels_established.load(Ordering::Relaxed),
            tunnel_failures: self.tunnel_failures.load(Ordering::Relaxed),
            tunnel_auth_failures: self.tunnel_auth_failures.load(Ordering::Relaxed),
            tunnel_timeouts: self.tunnel_timeouts.load(Ordering::Relaxed),
            tunnel_early_closes: self.tunnel_early_closes.load(Ordering::Relaxed),
            active_tunnels: self.active_tunnels.load(Ordering::Relaxed),
            last_activity_at_ns: self.last_activity_at_ns.load(Ordering::Relaxed),
        }
    }

    fn touch(&self) {
        update_atomic_u64_max(
            &self.last_activity_at_ns,
            duration_as_nanos(self.started_at.elapsed()),
        );
    }
}

impl ProxyConnectionAttempt {
    pub fn opened(mut self) -> ProxyConnectionLease {
        self.metrics.connection_opened();
        self.finished = true;
        ProxyConnectionLease {
            metrics: Arc::clone(&self.metrics),
            tunnel_active: false,
        }
    }
}

impl Drop for ProxyConnectionAttempt {
    fn drop(&mut self) {
        if !self.finished {
            self.metrics.connection_open_failed();
        }
    }
}

impl Drop for ProxyConnectionLease {
    fn drop(&mut self) {
        self.metrics.connection_closed(self.tunnel_active);
    }
}

impl ProxyTunnelAttempt {
    pub fn established(mut self, connection: &mut ProxyConnectionLease) {
        debug_assert!(Arc::ptr_eq(&self.metrics, &connection.metrics));
        self.metrics.tunnel_established();
        connection.tunnel_active = true;
        self.finished = true;
    }

    pub fn failed(mut self, kind: ProxyTunnelFailureKind) {
        self.metrics.tunnel_failed(kind);
        self.finished = true;
    }
}

impl Drop for ProxyTunnelAttempt {
    fn drop(&mut self) {
        if !self.finished {
            self.metrics.tunnel_failed(ProxyTunnelFailureKind::Other);
        }
    }
}

impl Metrics {
    pub fn proxy_endpoint_metrics(&self, endpoint: &str) -> Arc<ProxyEndpointMetrics> {
        self.proxy_registry.metrics_for(endpoint)
    }

    pub fn proxy_diagnostics_snapshot(&self) -> ProxyDiagnosticsSnapshot {
        ProxyDiagnosticsSnapshot {
            metadata: self.next_telemetry_snapshot_metadata(),
            endpoints: self.proxy_registry.snapshots(),
        }
    }
}
