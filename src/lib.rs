#![deny(unsafe_code)]
#![warn(clippy::pedantic)]
#![allow(clippy::module_name_repetitions)]

mod core;
mod errors;
mod messages;
mod py;

use pyo3::prelude::*;

#[pymodule(name = "_foghttp")]
fn foghttp_module(py: Python<'_>, module: &Bound<'_, PyModule>) -> PyResult<()> {
    py::register(module)?;
    errors::register(py, module)?;
    Ok(())
}
