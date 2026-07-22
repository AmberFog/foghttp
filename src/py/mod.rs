mod client;
mod pool_diagnostics;
mod response;
mod retry;
mod stats;
mod transport_state;
mod url;

use pyo3::prelude::*;

pub use client::{RawClient, RawStreamResponse, RawUploadBody};
pub use pool_diagnostics::{RawOriginPoolDiagnostics, RawPoolDiagnostics};
pub use response::{RawRequestInfo, RawResponse};
pub use retry::{RawRetryAttempt, RawRetryTrace};
pub use stats::{RawOriginPressure, RawStats};
pub use transport_state::RawTransportState;
pub use url::RawUrl;

pub fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<RawClient>()?;
    module.add_class::<RawStreamResponse>()?;
    module.add_class::<RawUploadBody>()?;
    module.add_class::<RawRequestInfo>()?;
    module.add_class::<RawResponse>()?;
    module.add_class::<RawRetryAttempt>()?;
    module.add_class::<RawRetryTrace>()?;
    module.add_class::<RawOriginPoolDiagnostics>()?;
    module.add_class::<RawPoolDiagnostics>()?;
    module.add_class::<RawOriginPressure>()?;
    module.add_class::<RawStats>()?;
    module.add_class::<RawTransportState>()?;
    module.add_class::<RawUrl>()?;
    Ok(())
}
