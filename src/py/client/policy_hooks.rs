use crate::core::policy::{PolicyRequest, RequestBodyPolicy, ResponseHead};
use pyo3::exceptions::PyTypeError;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyTuple};
use std::sync::Arc;

const POLICY_MODULE: &str = "foghttp.policy";
const REQUEST_VIEW: &str = "TransportPolicyRequest";
const RESPONSE_VIEW: &str = "TransportPolicyResponse";
const HOOK_RETURN_ERROR: &str = "transport policy hooks must return None";

pub(crate) struct PythonPolicyHooks {
    before_send: Option<Py<PyAny>>,
    on_response_headers: Option<Py<PyAny>>,
    after_response_body: Option<Py<PyAny>>,
    request_view: Py<PyAny>,
    response_view: Py<PyAny>,
}

impl PythonPolicyHooks {
    pub(crate) fn from_config(
        py: Python<'_>,
        config: Option<Py<PyAny>>,
    ) -> PyResult<Option<Arc<Self>>> {
        let Some(config) = config else {
            return Ok(None);
        };
        let config = config.bind(py);
        let before_send = optional_hook(config, "before_send")?;
        let on_response_headers = optional_hook(config, "on_response_headers")?;
        let after_response_body = optional_hook(config, "after_response_body")?;
        if before_send.is_none() && on_response_headers.is_none() && after_response_body.is_none() {
            return Ok(None);
        }

        let policy_module = py.import(POLICY_MODULE)?;
        Ok(Some(Arc::new(Self {
            before_send,
            on_response_headers,
            after_response_body,
            request_view: policy_module.getattr(REQUEST_VIEW)?.unbind(),
            response_view: policy_module.getattr(RESPONSE_VIEW)?.unbind(),
        })))
    }

    pub(crate) fn before_send(
        &self,
        request: PolicyRequest<'_>,
        redirect_hop: usize,
    ) -> PyResult<()> {
        let Some(callback) = self.before_send.as_ref() else {
            return Ok(());
        };
        Python::attach(|py| {
            let request = self.request_snapshot(py, request, redirect_hop)?;
            call_hook(py, callback, request)
        })
    }

    pub(crate) fn on_response_headers(
        &self,
        request: PolicyRequest<'_>,
        response: ResponseHead<'_>,
        redirect_hop: usize,
    ) -> PyResult<()> {
        let Some(callback) = self.on_response_headers.as_ref() else {
            return Ok(());
        };
        Python::attach(|py| {
            let response = self.response_snapshot(py, request, response, redirect_hop)?;
            call_hook(py, callback, response)
        })
    }

    pub(crate) fn after_response_body(
        &self,
        request: PolicyRequest<'_>,
        response: ResponseHead<'_>,
        redirect_hop: usize,
    ) -> PyResult<()> {
        let Some(callback) = self.after_response_body.as_ref() else {
            return Ok(());
        };
        Python::attach(|py| {
            let response = self.response_snapshot(py, request, response, redirect_hop)?;
            call_hook(py, callback, response)
        })
    }

    pub(crate) fn observes_response_body(&self) -> bool {
        self.after_response_body.is_some()
    }

    fn request_snapshot(
        &self,
        py: Python<'_>,
        request: PolicyRequest<'_>,
        redirect_hop: usize,
    ) -> PyResult<Py<PyAny>> {
        self.request_view
            .bind(py)
            .call1((
                request.method(),
                request.url().as_str(),
                request_body_state(request.body()),
                redirect_hop,
            ))
            .map(Bound::unbind)
    }

    fn response_snapshot(
        &self,
        py: Python<'_>,
        request: PolicyRequest<'_>,
        response: ResponseHead<'_>,
        redirect_hop: usize,
    ) -> PyResult<Py<PyAny>> {
        let request = self.request_snapshot(py, request, redirect_hop)?;
        let headers = PyTuple::new(
            py,
            response
                .headers()
                .iter()
                .map(|(name, value)| (name.as_str(), value.as_str())),
        )?;
        self.response_view
            .bind(py)
            .call1((request, response.status_code(), headers))
            .map(Bound::unbind)
    }
}

fn optional_hook(config: &Bound<'_, PyAny>, name: &str) -> PyResult<Option<Py<PyAny>>> {
    let hook = config.getattr(name)?;
    if hook.is_none() {
        return Ok(None);
    }
    if !hook.is_callable() {
        return Err(PyTypeError::new_err(format!(
            "{name} transport policy hook must be callable or None",
        )));
    }
    Ok(Some(hook.unbind()))
}

fn call_hook(py: Python<'_>, callback: &Py<PyAny>, view: Py<PyAny>) -> PyResult<()> {
    let result = callback.bind(py).call1((view,))?;
    if result.is_none() {
        return Ok(());
    }
    Err(PyTypeError::new_err(HOOK_RETURN_ERROR))
}

fn request_body_state(body: RequestBodyPolicy) -> &'static str {
    match body {
        RequestBodyPolicy::Empty => "empty",
        RequestBodyPolicy::NonReplayable => "non_replayable",
        RequestBodyPolicy::Replayable => "replayable",
    }
}
