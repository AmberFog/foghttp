mod client;
mod response;
mod stats;

use pyo3::prelude::*;

pub use client::RawClient;
pub use response::{RawRequestInfo, RawResponse};
pub use stats::RawStats;

pub fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<RawClient>()?;
    module.add_class::<RawRequestInfo>()?;
    module.add_class::<RawResponse>()?;
    module.add_class::<RawStats>()?;
    Ok(())
}
