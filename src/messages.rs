pub const POOL_ACQUIRE_QUEUE_FULL: &str = "request acquire queue is full";
pub const POOL_ACQUIRE_TIMEOUT: &str = "request acquire timeout expired";
pub const REQUEST_TOTAL_TIMEOUT: &str = "request total timeout expired";
pub const HTTPS_TO_HTTP_REDIRECT_BLOCKED: &str =
    "https-to-http redirect blocked by redirect security policy";
pub const TRUST_ENV_UNSUPPORTED: &str = "trust_env/proxy support is planned after the MVP";

pub fn response_body_too_large(limit: usize) -> String {
    format!("response body exceeded max_response_body_size of {limit} bytes")
}

pub fn buffered_response_body_budget_exceeded(limit: usize) -> String {
    format!("buffered response bodies exceeded max_buffered_response_bytes of {limit} bytes")
}

pub fn redirect_limit_exceeded(max_redirects: usize, url: &str) -> String {
    format!("redirect limit exceeded after {max_redirects} redirects for {url}")
}
