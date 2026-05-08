use crate::errors::FogHttpError;
use crate::messages::TRUST_ENV_UNSUPPORTED;
use pyo3::prelude::*;

pub fn validate_unsupported_options(trust_env: bool) -> PyResult<()> {
    if trust_env {
        return Err(FogHttpError::new_err(TRUST_ENV_UNSUPPORTED));
    }

    Ok(())
}
