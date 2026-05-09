use super::constants::{
    DEFAULT_RUNTIME_WORKER_CAP, MAX_RUNTIME_WORKERS, RUNTIME_WORKERS_ENV, RUNTIME_WORKERS_OPTION,
};
use crate::errors::FogHttpError;
use pyo3::prelude::*;
use std::env;

pub(super) fn runtime_workers(
    max_connections: usize,
    explicit_workers: Option<usize>,
) -> PyResult<usize> {
    if let Some(workers) = explicit_workers {
        return validate_runtime_workers(RUNTIME_WORKERS_OPTION, workers)
            .map_err(FogHttpError::new_err);
    }

    match env::var(RUNTIME_WORKERS_ENV) {
        Ok(value) => resolve_runtime_workers(max_connections, None, Some(value.as_str()))
            .map_err(FogHttpError::new_err),
        Err(env::VarError::NotPresent) => {
            resolve_runtime_workers(max_connections, None, None).map_err(FogHttpError::new_err)
        }
        Err(err) => Err(FogHttpError::new_err(err.to_string())),
    }
}

pub(super) fn resolve_runtime_workers(
    max_connections: usize,
    explicit_workers: Option<usize>,
    env_workers: Option<&str>,
) -> Result<usize, String> {
    if let Some(workers) = explicit_workers {
        return validate_runtime_workers(RUNTIME_WORKERS_OPTION, workers);
    }
    if let Some(value) = env_workers {
        let workers = value
            .parse::<usize>()
            .map_err(|_err| runtime_workers_error(RUNTIME_WORKERS_ENV))?;
        return validate_runtime_workers(RUNTIME_WORKERS_ENV, workers);
    }

    Ok(max_connections.clamp(1, DEFAULT_RUNTIME_WORKER_CAP))
}

fn validate_runtime_workers(source: &str, workers: usize) -> Result<usize, String> {
    if (1..=MAX_RUNTIME_WORKERS).contains(&workers) {
        return Ok(workers);
    }

    Err(runtime_workers_error(source))
}

fn runtime_workers_error(source: &str) -> String {
    format!("{source} must be an integer between 1 and {MAX_RUNTIME_WORKERS}")
}
