use pyo3::create_exception;
use pyo3::exceptions::PyException;
use pyo3::prelude::*;

create_exception!(_foghttp, FogHttpError, PyException);
create_exception!(_foghttp, FogHttpNetworkError, FogHttpError);
create_exception!(_foghttp, FogHttpSsrfError, FogHttpError);
create_exception!(_foghttp, FogHttpTimeoutError, FogHttpError);
create_exception!(_foghttp, FogHttpPoolTimeoutError, FogHttpTimeoutError);
create_exception!(_foghttp, FogHttpReadTimeoutError, FogHttpTimeoutError);
create_exception!(_foghttp, FogHttpWriteTimeoutError, FogHttpTimeoutError);
create_exception!(_foghttp, FogHttpLifecycleError, FogHttpError);
create_exception!(_foghttp, FogHttpResponseBodyTooLargeError, FogHttpError);
create_exception!(
    _foghttp,
    FogHttpResponseBodyBudgetExceededError,
    FogHttpError
);

/// Format a transport error including its source chain.
///
/// `hyper`/`hyper-util` errors keep the actionable cause (TLS validation
/// failure, proxy CONNECT rejection, refused connection) in `source()` while
/// the top-level `Display` is only a generic phase label such as
/// `client error (Connect)`. Surfacing the chain keeps the public error
/// diagnostic without leaking credentials, because the proxy connector never
/// places credentials in connection URIs or CONNECT-failure messages.
pub fn transport_error_message(error: &dyn std::error::Error) -> String {
    const MAX_DEPTH: usize = 5;
    let mut message = error.to_string();
    let mut source = error.source();
    let mut depth = 0;
    while let Some(cause) = source {
        if depth >= MAX_DEPTH {
            break;
        }
        let cause_text = cause.to_string();
        if !cause_text.is_empty() && !message.contains(&cause_text) {
            message.push_str(": ");
            message.push_str(&cause_text);
        }
        source = cause.source();
        depth += 1;
    }
    message
}

pub fn register(py: Python<'_>, module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("FogHttpError", py.get_type::<FogHttpError>())?;
    module.add("FogHttpNetworkError", py.get_type::<FogHttpNetworkError>())?;
    module.add("FogHttpSsrfError", py.get_type::<FogHttpSsrfError>())?;
    module.add("FogHttpTimeoutError", py.get_type::<FogHttpTimeoutError>())?;
    module.add(
        "FogHttpPoolTimeoutError",
        py.get_type::<FogHttpPoolTimeoutError>(),
    )?;
    module.add(
        "FogHttpReadTimeoutError",
        py.get_type::<FogHttpReadTimeoutError>(),
    )?;
    module.add(
        "FogHttpWriteTimeoutError",
        py.get_type::<FogHttpWriteTimeoutError>(),
    )?;
    module.add(
        "FogHttpLifecycleError",
        py.get_type::<FogHttpLifecycleError>(),
    )?;
    module.add(
        "FogHttpResponseBodyTooLargeError",
        py.get_type::<FogHttpResponseBodyTooLargeError>(),
    )?;
    module.add(
        "FogHttpResponseBodyBudgetExceededError",
        py.get_type::<FogHttpResponseBodyBudgetExceededError>(),
    )?;
    Ok(())
}
