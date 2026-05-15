use pyo3::create_exception;
use pyo3::exceptions::PyException;
use pyo3::prelude::*;

create_exception!(_foghttp, FogHttpError, PyException);
create_exception!(_foghttp, FogHttpTimeoutError, FogHttpError);
create_exception!(_foghttp, FogHttpResponseBodyTooLargeError, FogHttpError);

pub fn register(py: Python<'_>, module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("FogHttpError", py.get_type::<FogHttpError>())?;
    module.add("FogHttpTimeoutError", py.get_type::<FogHttpTimeoutError>())?;
    module.add(
        "FogHttpResponseBodyTooLargeError",
        py.get_type::<FogHttpResponseBodyTooLargeError>(),
    )?;
    Ok(())
}
