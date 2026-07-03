mod constants;
mod workers;

#[cfg(test)]
mod tests;

use crate::errors::FogHttpError;
use crate::messages::{RUNTIME_INVALID, RUNTIME_WORKERS_SHARED_UNSUPPORTED};
use pyo3::prelude::*;
use std::sync::OnceLock;
use tokio::runtime::{Builder, Runtime};
use workers::runtime_workers;

pub enum ClientRuntime {
    Shared(&'static Runtime),
    Dedicated(Runtime),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RuntimeMode {
    Shared,
    Dedicated,
}

static SHARED_RUNTIME: OnceLock<Runtime> = OnceLock::new();

impl ClientRuntime {
    pub fn build(
        max_active_requests: usize,
        mode: RuntimeMode,
        explicit_workers: Option<usize>,
    ) -> PyResult<Self> {
        match mode {
            RuntimeMode::Shared => {
                if explicit_workers.is_some() {
                    return Err(FogHttpError::new_err(RUNTIME_WORKERS_SHARED_UNSUPPORTED));
                }
                shared_runtime().map(Self::Shared)
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

fn shared_runtime() -> PyResult<&'static Runtime> {
    if let Some(runtime) = SHARED_RUNTIME.get() {
        return Ok(runtime);
    }

    let worker_threads = shared_runtime_workers();
    let runtime = build_multi_thread_runtime(worker_threads)?;
    let _result = SHARED_RUNTIME.set(runtime);
    SHARED_RUNTIME
        .get()
        .ok_or_else(|| FogHttpError::new_err("shared runtime initialization failed"))
}

fn build_multi_thread_runtime(worker_threads: usize) -> PyResult<Runtime> {
    Builder::new_multi_thread()
        .worker_threads(worker_threads)
        .enable_all()
        .build()
        .map_err(|err| FogHttpError::new_err(err.to_string()))
}

fn shared_runtime_workers() -> usize {
    let parallelism = std::thread::available_parallelism().ok().map(usize::from);
    shared_runtime_workers_from_parallelism(parallelism)
}

fn shared_runtime_workers_from_parallelism(parallelism: Option<usize>) -> usize {
    parallelism
        .unwrap_or(constants::SHARED_RUNTIME_WORKER_FALLBACK)
        .clamp(1, constants::DEFAULT_RUNTIME_WORKER_CAP)
}
