use crate::errors::FogHttpError;
use http_body_util::BodyExt;
use hyper::body::Incoming;
use pyo3::prelude::*;

pub async fn collect_body(body: Incoming) -> PyResult<Vec<u8>> {
    let collected = body
        .collect()
        .await
        .map_err(|err| FogHttpError::new_err(err.to_string()))?;

    Ok(collected.to_bytes().to_vec())
}
