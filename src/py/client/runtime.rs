use crate::errors::FogHttpError;
use pyo3::prelude::*;
use tokio::runtime::{Builder, Runtime};

pub fn build_runtime(max_connections: usize) -> PyResult<Runtime> {
    Builder::new_multi_thread()
        .worker_threads(max_connections.clamp(1, 32))
        .enable_all()
        .build()
        .map_err(|err| FogHttpError::new_err(err.to_string()))
}
