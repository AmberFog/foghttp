use crate::core::headers::HeaderPairs;
use crate::core::url::HttpUrl;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum RequestBodyPolicy {
    Empty,
    NonReplayable,
    Replayable,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum RequestBodyMutation {
    Drop,
    Preserve,
}

impl RequestBodyPolicy {
    pub(crate) fn from_request(has_body: bool, replayable: bool) -> Self {
        match (has_body, replayable) {
            (false, _) => Self::Empty,
            (true, true) => Self::Replayable,
            (true, false) => Self::NonReplayable,
        }
    }

    pub(crate) fn can_replay(self) -> bool {
        self != Self::NonReplayable
    }
}

#[derive(Clone, Copy)]
pub(crate) struct PolicyRequest<'a> {
    body: RequestBodyPolicy,
    method: &'a str,
    url: &'a HttpUrl,
}

impl<'a> PolicyRequest<'a> {
    pub(crate) fn new(method: &'a str, url: &'a HttpUrl, body: RequestBodyPolicy) -> Self {
        Self { body, method, url }
    }

    pub(crate) fn body(self) -> RequestBodyPolicy {
        self.body
    }

    pub(crate) fn method(self) -> &'a str {
        self.method
    }

    pub(crate) fn url(self) -> &'a HttpUrl {
        self.url
    }
}

#[derive(Clone, Copy)]
pub(crate) struct ResponseHead<'a> {
    headers: &'a HeaderPairs,
    status_code: u16,
}

impl<'a> ResponseHead<'a> {
    pub(crate) fn new(status_code: u16, headers: &'a HeaderPairs) -> Self {
        Self {
            headers,
            status_code,
        }
    }

    pub(crate) fn headers(self) -> &'a HeaderPairs {
        self.headers
    }

    pub(crate) fn status_code(self) -> u16 {
        self.status_code
    }
}
