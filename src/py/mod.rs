mod client;
mod response;
mod stats;

use pyo3::prelude::*;

pub use client::RawClient;
pub use response::RawResponse;
pub use stats::RawStats;

pub fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<RawClient>()?;
    module.add_class::<RawResponse>()?;
    module.add_class::<RawStats>()?;
    Ok(())
}
