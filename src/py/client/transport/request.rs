use crate::core::headers::HeaderPairs;
use crate::core::request::RequestParts;
use crate::core::response::BufferedBodyBudget;
use crate::core::url::HttpUrl;
use crate::errors::FogHttpError;
use crate::messages::NON_REPLAYABLE_REQUEST_BODY_REDIRECT;
use crate::py::client::body::BodyReplayability;
use crate::py::client::redirects::{redirect_headers, RedirectAction, RedirectHeaderPolicy};
use crate::py::response::RawRequestInfo;
use pyo3::prelude::*;

pub struct TransportRequest {
    pub method: String,
    pub url: String,
    pub headers: HeaderPairs,
    pub body: Option<Vec<u8>>,
    pub body_replayable: bool,
    pub total_timeout: f64,
    pub read_timeout: f64,
    pub max_response_body_size: Option<usize>,
    pub buffered_body_budget: BufferedBodyBudget,
    pub follow_redirects: bool,
    pub max_redirects: usize,
}

pub(super) struct RequestState {
    pub(super) method: String,
    pub(super) url: String,
    pub(super) headers: HeaderPairs,
    pub(super) body: Option<Vec<u8>>,
    pub(super) body_replayability: BodyReplayability,
    pub(super) total_timeout: f64,
    pub(super) read_timeout: f64,
    pub(super) max_response_body_size: Option<usize>,
    pub(super) buffered_body_budget: BufferedBodyBudget,
    pub(super) follow_redirects: bool,
    pub(super) max_redirects: usize,
}

impl RequestState {
    pub(super) fn request_parts(&self) -> RequestParts {
        RequestParts {
            method: self.method.clone(),
            url: self.url.clone(),
            headers: self.headers.clone(),
            body: self.body.clone(),
        }
    }

    pub(super) fn request_info(&self) -> RawRequestInfo {
        RawRequestInfo {
            method: self.method.clone(),
            url: self.url.clone(),
            headers: self.headers.clone(),
        }
    }

    pub(super) fn origin(&self) -> PyResult<String> {
        HttpUrl::parse(&self.url)
            .map(|url| url.origin())
            .map_err(FogHttpError::new_err)
    }

    pub(super) fn apply_redirect(&mut self, redirect: RedirectAction) -> PyResult<()> {
        if redirect.preserve_body && self.body.is_some() && !self.body_replayability.can_replay() {
            return Err(FogHttpError::new_err(NON_REPLAYABLE_REQUEST_BODY_REDIRECT));
        }

        self.method = redirect.method;
        self.url = redirect.url;
        self.headers = redirect_headers(
            std::mem::take(&mut self.headers),
            RedirectHeaderPolicy {
                preserve_body: redirect.preserve_body,
                remove_sensitive_headers: redirect.remove_sensitive_headers,
            },
        );

        if !redirect.preserve_body {
            self.body = None;
            self.body_replayability = BodyReplayability::Replayable;
        }
        Ok(())
    }

    pub(super) fn try_from(parts: TransportRequest) -> PyResult<Self> {
        let url = HttpUrl::parse(&parts.url).map_err(FogHttpError::new_err)?;
        let body_replayability =
            BodyReplayability::from_buffered_body(parts.body.as_deref(), parts.body_replayable);

        Ok(Self {
            method: parts.method.to_uppercase(),
            url: url.as_str().to_owned(),
            headers: parts.headers,
            body: parts.body,
            body_replayability,
            total_timeout: parts.total_timeout,
            read_timeout: parts.read_timeout,
            max_response_body_size: parts.max_response_body_size,
            buffered_body_budget: parts.buffered_body_budget,
            follow_redirects: parts.follow_redirects,
            max_redirects: parts.max_redirects,
        })
    }
}
