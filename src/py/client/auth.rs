use crate::core::headers::HeaderPairs;
use hyper::header::HeaderValue;
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyTuple};
use std::sync::Arc;

const AUTH_MODULE: &str = "foghttp.auth";
const AUTH_REQUEST: &str = "AuthRequest";
const INTERNAL_AUTH_MODULE: &str = "foghttp._client.auth";
const NORMALIZE_AUTH_HEADERS: &str = "_normalize_auth_header_pairs";
const VALIDATE_SYNC_AUTH_HOOK: &str = "_validate_sync_hook";

pub(crate) struct PythonAuth {
    provider: AuthProvider,
}

enum AuthProvider {
    Basic(String),
    Hook {
        callback: Py<PyAny>,
        normalize_headers: Py<PyAny>,
        request_view: Py<PyAny>,
    },
}

impl PythonAuth {
    pub(crate) fn from_config(
        py: Python<'_>,
        basic_authorization: Option<String>,
        hook: Option<Py<PyAny>>,
    ) -> PyResult<Option<Arc<Self>>> {
        let provider = match (basic_authorization, hook) {
            (None, None) => return Ok(None),
            (Some(header), None) => {
                validate_basic_authorization(&header)?;
                AuthProvider::Basic(header)
            }
            (None, Some(callback)) => {
                if !callback.bind(py).is_callable() {
                    return Err(PyTypeError::new_err("auth hook must be callable"));
                }
                let auth_helpers = py.import(INTERNAL_AUTH_MODULE)?;
                auth_helpers
                    .getattr(VALIDATE_SYNC_AUTH_HOOK)?
                    .call1((callback.bind(py),))?;
                AuthProvider::Hook {
                    callback,
                    normalize_headers: auth_helpers.getattr(NORMALIZE_AUTH_HEADERS)?.unbind(),
                    request_view: py.import(AUTH_MODULE)?.getattr(AUTH_REQUEST)?.unbind(),
                }
            }
            (Some(_), Some(_)) => {
                return Err(PyValueError::new_err(
                    "basic auth and callable auth cannot be enabled together",
                ));
            }
        };
        Ok(Some(Arc::new(Self { provider })))
    }

    pub(crate) fn uses_hook(&self) -> bool {
        matches!(self.provider, AuthProvider::Hook { .. })
    }

    pub(crate) fn header_updates(
        &self,
        method: &str,
        url: &str,
        headers: &HeaderPairs,
        redirect_hop: usize,
        extensions: Option<&Py<PyAny>>,
    ) -> PyResult<HeaderPairs> {
        match &self.provider {
            AuthProvider::Basic(header) => Ok(vec![("Authorization".to_owned(), header.clone())]),
            AuthProvider::Hook {
                callback,
                normalize_headers,
                request_view,
            } => Python::attach(|py| {
                let headers = PyTuple::new(
                    py,
                    headers
                        .iter()
                        .map(|(name, value)| (name.as_str(), value.as_str())),
                )?;
                let request_view = request_view.bind(py);
                let request = match extensions {
                    Some(extensions) => request_view.call1((
                        method,
                        url,
                        headers,
                        redirect_hop,
                        extensions.bind(py),
                    ))?,
                    None => request_view.call1((method, url, headers, redirect_hop))?,
                };
                let result = callback.bind(py).call1((request,))?;
                normalize_headers
                    .bind(py)
                    .call1((result,))?
                    .extract::<HeaderPairs>()
            }),
        }
    }
}

fn validate_basic_authorization(value: &str) -> PyResult<()> {
    let header = HeaderValue::from_str(value)
        .map_err(|_| PyValueError::new_err("basic authorization header is invalid"))?;
    header
        .to_str()
        .map_err(|_| PyValueError::new_err("basic authorization header is invalid"))?;
    Ok(())
}
