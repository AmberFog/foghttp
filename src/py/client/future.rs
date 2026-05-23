use crate::py::client::streams::RawStreamResponse;
use crate::py::response::RawResponse;
use pyo3::exceptions::PyBaseException;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyBytes};

pub fn cancel_python_future(loop_: &Py<PyAny>, future: &Py<PyAny>) {
    Python::attach(|py| {
        if let Err(err) = schedule_cancel(py, loop_, future) {
            err.write_unraisable(py, Some(future.bind(py)));
        }
    });
}

pub fn complete_python_future(
    loop_: &Py<PyAny>,
    future: &Py<PyAny>,
    result: PyResult<RawResponse>,
) {
    Python::attach(|py| {
        let call_result: PyResult<()> = match result {
            Ok(response) => schedule_set_result(py, loop_, future, response),
            Err(err) => {
                let exception = err.into_value(py);
                schedule_set_exception(py, loop_, future, exception)
            }
        };

        if let Err(err) = call_result {
            err.write_unraisable(py, Some(future.bind(py)));
        }
    });
}

pub fn complete_python_stream_future(
    loop_: &Py<PyAny>,
    future: &Py<PyAny>,
    result: PyResult<RawStreamResponse>,
) {
    Python::attach(|py| {
        let call_result: PyResult<()> = match result {
            Ok(response) => schedule_set_stream_result(py, loop_, future, response),
            Err(err) => {
                let exception = err.into_value(py);
                schedule_set_exception(py, loop_, future, exception)
            }
        };

        if let Err(err) = call_result {
            err.write_unraisable(py, Some(future.bind(py)));
        }
    });
}

pub fn complete_python_bytes_future(
    loop_: &Py<PyAny>,
    future: &Py<PyAny>,
    result: PyResult<Option<Vec<u8>>>,
) {
    Python::attach(|py| {
        let call_result: PyResult<()> = match result {
            Ok(Some(chunk)) => schedule_set_bytes_result(py, loop_, future, &chunk),
            Ok(None) => schedule_set_none_result(py, loop_, future),
            Err(err) => {
                let exception = err.into_value(py);
                schedule_set_exception(py, loop_, future, exception)
            }
        };

        if let Err(err) = call_result {
            err.write_unraisable(py, Some(future.bind(py)));
        }
    });
}

fn schedule_cancel(py: Python<'_>, loop_: &Py<PyAny>, future: &Py<PyAny>) -> PyResult<()> {
    let helper = py
        .import("foghttp._client.asyncio_futures")?
        .getattr("cancel_if_pending")?;
    loop_
        .bind(py)
        .call_method1("call_soon_threadsafe", (helper, future.bind(py)))?;
    Ok(())
}

fn schedule_set_bytes_result(
    py: Python<'_>,
    loop_: &Py<PyAny>,
    future: &Py<PyAny>,
    chunk: &[u8],
) -> PyResult<()> {
    let helper = py
        .import("foghttp._client.asyncio_futures")?
        .getattr("set_result_if_pending")?;
    let chunk = PyBytes::new(py, chunk);
    loop_
        .bind(py)
        .call_method1("call_soon_threadsafe", (helper, future.bind(py), chunk))?;
    Ok(())
}

fn schedule_set_none_result(py: Python<'_>, loop_: &Py<PyAny>, future: &Py<PyAny>) -> PyResult<()> {
    let helper = py
        .import("foghttp._client.asyncio_futures")?
        .getattr("set_result_if_pending")?;
    loop_
        .bind(py)
        .call_method1("call_soon_threadsafe", (helper, future.bind(py), py.None()))?;
    Ok(())
}

fn schedule_set_exception(
    py: Python<'_>,
    loop_: &Py<PyAny>,
    future: &Py<PyAny>,
    exception: Py<PyBaseException>,
) -> PyResult<()> {
    let helper = py
        .import("foghttp._client.asyncio_futures")?
        .getattr("set_exception_if_pending")?;
    loop_
        .bind(py)
        .call_method1("call_soon_threadsafe", (helper, future.bind(py), exception))?;
    Ok(())
}

fn schedule_set_stream_result(
    py: Python<'_>,
    loop_: &Py<PyAny>,
    future: &Py<PyAny>,
    response: RawStreamResponse,
) -> PyResult<()> {
    let helper = py
        .import("foghttp._client.asyncio_futures")?
        .getattr("set_result_if_pending")?;
    let response = Py::new(py, response)?;
    loop_
        .bind(py)
        .call_method1("call_soon_threadsafe", (helper, future.bind(py), response))?;
    Ok(())
}

fn schedule_set_result(
    py: Python<'_>,
    loop_: &Py<PyAny>,
    future: &Py<PyAny>,
    response: RawResponse,
) -> PyResult<()> {
    let helper = py
        .import("foghttp._client.asyncio_futures")?
        .getattr("set_result_if_pending")?;
    let response = Py::new(py, response)?;
    loop_
        .bind(py)
        .call_method1("call_soon_threadsafe", (helper, future.bind(py), response))?;
    Ok(())
}
