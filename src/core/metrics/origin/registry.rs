use super::metrics::OriginMetrics;
use super::snapshots::{OriginMetricsSnapshot, OriginPoolDiagnosticsSnapshot};
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, PoisonError, RwLock, RwLockReadGuard, RwLockWriteGuard};
use std::time::Instant;

const ORIGIN_PRESSURE_CLEANUP_THRESHOLD: usize = 1024;

pub struct OriginMetricsRegistry {
    started_at: Instant,
    origins: RwLock<HashMap<String, Arc<OriginMetrics>>>,
    pruned_idle_origins: AtomicBool,
}

impl Default for OriginMetricsRegistry {
    fn default() -> Self {
        Self {
            started_at: Instant::now(),
            origins: RwLock::new(HashMap::new()),
            pruned_idle_origins: AtomicBool::new(false),
        }
    }
}

impl OriginMetricsRegistry {
    pub fn metrics_for(&self, origin: &str) -> Arc<OriginMetrics> {
        if let Some(metrics) = self.read_origins().get(origin) {
            return Arc::clone(metrics);
        }

        let mut origins = self.write_origins();
        if let Some(metrics) = origins.get(origin) {
            return Arc::clone(metrics);
        }

        if origins.len() >= ORIGIN_PRESSURE_CLEANUP_THRESHOLD {
            let origin_count_before_cleanup = origins.len();
            origins.retain(|_origin, metrics| !metrics.is_idle());
            if origins.len() < origin_count_before_cleanup {
                self.pruned_idle_origins.store(true, Ordering::Release);
            }
        }

        let metrics = Arc::new(OriginMetrics::new(origin.to_owned(), self.started_at));
        origins.insert(origin.to_owned(), Arc::clone(&metrics));
        metrics
    }

    pub fn snapshots(&self) -> Vec<OriginMetricsSnapshot> {
        let origins = self.read_origins();
        let mut snapshots = origins
            .values()
            .map(|metrics| metrics.snapshot())
            .collect::<Vec<_>>();
        snapshots.sort_by(|left, right| left.origin.cmp(&right.origin));
        snapshots
    }

    pub fn snapshots_include_all_historical_origins(&self) -> bool {
        !self.pruned_idle_origins.load(Ordering::Acquire)
    }

    pub fn pool_diagnostics_snapshots(&self) -> Vec<OriginPoolDiagnosticsSnapshot> {
        let origins = self.read_origins();
        let mut snapshots = origins
            .values()
            .map(|metrics| metrics.pool_diagnostics_snapshot())
            .collect::<Vec<_>>();
        snapshots.sort_by(|left, right| left.origin.cmp(&right.origin));
        snapshots
    }

    fn read_origins(&self) -> RwLockReadGuard<'_, HashMap<String, Arc<OriginMetrics>>> {
        self.origins.read().unwrap_or_else(PoisonError::into_inner)
    }

    fn write_origins(&self) -> RwLockWriteGuard<'_, HashMap<String, Arc<OriginMetrics>>> {
        self.origins.write().unwrap_or_else(PoisonError::into_inner)
    }
}
