use crate::errors::FogHttpError;
use pyo3::prelude::*;
use std::env;
use tokio::runtime::{Builder, Runtime};

const MAX_RUNTIME_WORKERS: usize = 32;
const RUNTIME_WORKERS_ENV: &str = "FOGHTTP_RUNTIME_WORKERS";

pub fn build_runtime(max_connections: usize) -> PyResult<Runtime> {
    let worker_threads = runtime_workers(max_connections)?;
    Builder::new_multi_thread()
        .worker_threads(worker_threads)
        .enable_all()
        .build()
        .map_err(|err| FogHttpError::new_err(err.to_string()))
}

fn runtime_workers(max_connections: usize) -> PyResult<usize> {
    match env::var(RUNTIME_WORKERS_ENV) {
        Ok(value) => {
            let workers = value.parse::<usize>().map_err(|_err| {
                FogHttpError::new_err(format!("{RUNTIME_WORKERS_ENV} must be a positive integer"))
            })?;
            if workers == 0 {
                return Err(FogHttpError::new_err(format!(
                    "{RUNTIME_WORKERS_ENV} must be a positive integer",
                )));
            }
            Ok(workers.min(MAX_RUNTIME_WORKERS))
        }
        Err(env::VarError::NotPresent) => Ok(max_connections.clamp(1, MAX_RUNTIME_WORKERS)),
        Err(err) => Err(FogHttpError::new_err(err.to_string())),
    }
}
