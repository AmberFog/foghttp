pub const POOL_ACQUIRE_QUEUE_FULL: &str = "request acquire queue is full";
pub const POOL_ACQUIRE_TIMEOUT: &str = "request acquire timeout expired";
pub const REQUEST_BODY_WRITE_TIMEOUT: &str = "request body write timeout expired";
pub const RESPONSE_BODY_READ_TIMEOUT: &str = "response body read timeout expired";
pub const STREAM_REQUEST_TASK_START_FAILED: &str = "async stream request task failed to start";
pub const STREAM_RESPONSE_READ_ABORTED: &str = "stream response body read was aborted";
pub const REQUEST_TOTAL_TIMEOUT: &str = "request total timeout expired";
pub const HTTPS_TO_HTTP_REDIRECT_BLOCKED: &str =
    "https-to-http redirect blocked by redirect security policy";
pub const NON_REPLAYABLE_REQUEST_BODY_REDIRECT: &str =
    "cannot follow redirect with non-replayable request body";
pub const PROXY_REDIRECT_POLICY_RECOMPUTE_UNSUPPORTED: &str =
    "cross-origin redirect with environment proxy policy requires per-hop proxy decisions";
pub const PROXY_CONNECT_CLOSED: &str =
    "proxy closed the connection before the CONNECT tunnel was established";
pub const PROXY_CONNECT_INVALID_RESPONSE: &str =
    "proxy returned an invalid response to the CONNECT request";
pub const PROXY_CONNECT_TIMEOUT: &str = "proxy CONNECT tunnel setup timed out";
pub const PROXY_ENDPOINT_MISSING_HOST: &str = "proxy URL must include a host";
pub const PROXY_ENDPOINT_PATH_OR_QUERY_UNSUPPORTED: &str =
    "proxy URL must not include path or query";
pub const PROXY_ENDPOINT_SCHEME_UNSUPPORTED: &str = "proxy URL scheme must be http";
pub const PROXY_ENDPOINT_USERINFO_UNSUPPORTED: &str = "proxy URL must not include userinfo";
pub const RUNTIME_INVALID: &str = "runtime must be 'shared' or 'dedicated'";
pub const RUNTIME_WORKERS_SHARED_UNSUPPORTED: &str = "runtime_workers requires runtime='dedicated'";

pub fn proxy_connect_rejected(status: u16) -> String {
    format!("proxy rejected the CONNECT tunnel with status {status}")
}

pub fn response_body_too_large(limit: usize) -> String {
    format!("response body exceeded max_response_body_size of {limit} bytes")
}

pub fn buffered_response_body_budget_exceeded(limit: usize) -> String {
    format!("buffered response bodies exceeded max_buffered_response_bytes of {limit} bytes")
}

pub fn redirect_limit_exceeded(max_redirects: usize, url: &str) -> String {
    format!("redirect limit exceeded after {max_redirects} redirects for {url}")
}
