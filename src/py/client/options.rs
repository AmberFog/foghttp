use crate::errors::FogHttpError;
use crate::messages::{REDIRECTS_UNSUPPORTED, TRUST_ENV_UNSUPPORTED};
use pyo3::prelude::*;

pub fn validate_unsupported_options(follow_redirects: bool, trust_env: bool) -> PyResult<()> {
    if follow_redirects {
        return Err(FogHttpError::new_err(REDIRECTS_UNSUPPORTED));
    }

    if trust_env {
        return Err(FogHttpError::new_err(TRUST_ENV_UNSUPPORTED));
    }

    Ok(())
}
