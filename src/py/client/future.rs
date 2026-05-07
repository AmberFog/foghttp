use crate::py::response::RawResponse;
use pyo3::prelude::*;
use pyo3::types::PyAny;

pub fn complete_python_future(
    loop_: &Py<PyAny>,
    future: &Py<PyAny>,
    result: PyResult<RawResponse>,
) {
    Python::attach(|py| {
        let call_result: PyResult<()> = match result {
            Ok(response) => Py::new(py, response).and_then(|response| {
                let setter = future.bind(py).getattr("set_result")?;
                loop_
                    .bind(py)
                    .call_method1("call_soon_threadsafe", (setter, response))?;
                Ok(())
            }),
            Err(err) => {
                let exception = err.into_value(py);
                future.bind(py).getattr("set_exception").and_then(|setter| {
                    loop_
                        .bind(py)
                        .call_method1("call_soon_threadsafe", (setter, exception))?;
                    Ok(())
                })
            }
        };

        if let Err(err) = call_result {
            err.write_unraisable(py, Some(future.bind(py)));
        }
    });
}
