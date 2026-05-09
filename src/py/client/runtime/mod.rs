mod constants;
mod workers;

#[cfg(test)]
mod tests;

use crate::errors::FogHttpError;
use pyo3::prelude::*;
use tokio::runtime::{Builder, Runtime};
use workers::runtime_workers;

pub fn build_runtime(max_connections: usize, explicit_workers: Option<usize>) -> PyResult<Runtime> {
    let worker_threads = runtime_workers(max_connections, explicit_workers)?;
    Builder::new_multi_thread()
        .worker_threads(worker_threads)
        .enable_all()
        .build()
        .map_err(|err| FogHttpError::new_err(err.to_string()))
}
