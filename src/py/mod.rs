mod client;
mod response;
mod stats;
mod url;

use pyo3::prelude::*;

pub use client::RawClient;
pub use response::{RawRequestInfo, RawResponse};
pub use stats::{RawOriginPressure, RawStats};
pub use url::RawUrl;

pub fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<RawClient>()?;
    module.add_class::<RawRequestInfo>()?;
    module.add_class::<RawResponse>()?;
    module.add_class::<RawOriginPressure>()?;
    module.add_class::<RawStats>()?;
    module.add_class::<RawUrl>()?;
    Ok(())
}
