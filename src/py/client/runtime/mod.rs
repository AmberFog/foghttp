mod constants;
mod shared;
mod workers;

#[cfg(test)]
mod tests;

use crate::errors::FogHttpError;
use crate::messages::{RUNTIME_INVALID, RUNTIME_WORKERS_SHARED_UNSUPPORTED};
use pyo3::prelude::*;
use shared::shared_runtime;
use std::sync::Arc;
use tokio::runtime::{Builder, Runtime};
use workers::runtime_workers;

pub enum ClientRuntime {
    Shared(Arc<Runtime>),
    Dedicated(Runtime),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RuntimeMode {
    Shared,
    Dedicated,
}

impl ClientRuntime {
    pub fn build(
        py: Python<'_>,
        max_active_requests: usize,
        mode: RuntimeMode,
        explicit_workers: Option<usize>,
    ) -> PyResult<Self> {
        match mode {
            RuntimeMode::Shared => {
                if explicit_workers.is_some() {
                    return Err(FogHttpError::new_err(RUNTIME_WORKERS_SHARED_UNSUPPORTED));
                }
                shared_runtime(py).map(Self::Shared)
            }
            RuntimeMode::Dedicated => {
                build_dedicated_runtime(max_active_requests, explicit_workers).map(Self::Dedicated)
            }
        }
    }

    pub fn runtime(&self) -> &Runtime {
        match self {
            Self::Shared(runtime) => runtime,
            Self::Dedicated(runtime) => runtime,
        }
    }

    pub fn shutdown_background(self) {
        if let Self::Dedicated(runtime) = self {
            runtime.shutdown_background();
        }
    }

    pub fn abandon_without_shutdown(self) {
        std::mem::forget(self);
    }
}

pub fn parse_runtime_mode(value: &str) -> PyResult<RuntimeMode> {
    match value {
        "shared" => Ok(RuntimeMode::Shared),
        "dedicated" => Ok(RuntimeMode::Dedicated),
        _ => Err(FogHttpError::new_err(RUNTIME_INVALID)),
    }
}

fn build_dedicated_runtime(
    max_active_requests: usize,
    explicit_workers: Option<usize>,
) -> PyResult<Runtime> {
    let worker_threads = runtime_workers(max_active_requests, explicit_workers)?;
    build_multi_thread_runtime(worker_threads)
}

pub(super) fn build_multi_thread_runtime(worker_threads: usize) -> PyResult<Runtime> {
    Builder::new_multi_thread()
        .worker_threads(worker_threads)
        .enable_all()
        .build()
        .map_err(|err| FogHttpError::new_err(err.to_string()))
}

pub(super) fn shared_runtime_workers() -> usize {
    let parallelism = std::thread::available_parallelism().ok().map(usize::from);
    shared_runtime_workers_from_parallelism(parallelism)
}

fn shared_runtime_workers_from_parallelism(parallelism: Option<usize>) -> usize {
    parallelism
        .unwrap_or(constants::SHARED_RUNTIME_WORKER_FALLBACK)
        .clamp(1, constants::DEFAULT_RUNTIME_WORKER_CAP)
}
