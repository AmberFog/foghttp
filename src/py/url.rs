use crate::core::url::HttpUrl;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

#[pyclass(skip_from_py_object)]
#[derive(Clone)]
pub struct RawUrl {
    inner: HttpUrl,
}

#[pymethods]
impl RawUrl {
    #[new]
    fn new(url: &str) -> PyResult<Self> {
        Ok(Self {
            inner: HttpUrl::parse(url).map_err(PyValueError::new_err)?,
        })
    }

    #[getter]
    fn value(&self) -> String {
        self.inner.as_str().to_owned()
    }

    #[getter]
    fn scheme(&self) -> String {
        self.inner.scheme().to_owned()
    }

    #[getter]
    fn host(&self) -> String {
        self.inner.host()
    }

    #[getter]
    fn port(&self) -> u16 {
        self.inner.port()
    }

    #[getter]
    fn path(&self) -> String {
        self.inner.path().to_owned()
    }

    #[getter]
    fn query(&self) -> String {
        self.inner.query().to_owned()
    }

    #[getter]
    fn fragment(&self) -> String {
        self.inner.fragment().to_owned()
    }

    #[getter]
    fn origin(&self) -> String {
        self.inner.origin()
    }

    fn join(&self, location: &str) -> PyResult<Self> {
        Ok(Self {
            inner: self.inner.join(location).map_err(PyValueError::new_err)?,
        })
    }

    fn is_same_origin(&self, other: &Self) -> bool {
        self.inner.is_same_origin(&other.inner)
    }

    fn __str__(&self) -> String {
        self.value()
    }

    fn __repr__(&self) -> String {
        format!("RawUrl({:?})", self.value())
    }
}
