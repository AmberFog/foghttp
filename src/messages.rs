pub const POOL_ACQUIRE_QUEUE_FULL: &str = "request acquire queue is full";
pub const POOL_ACQUIRE_TIMEOUT: &str = "request acquire timeout expired";
pub const REQUEST_TOTAL_TIMEOUT: &str = "request total timeout expired";
pub const TRUST_ENV_UNSUPPORTED: &str = "trust_env/proxy support is planned after the MVP";

pub fn redirect_limit_exceeded(max_redirects: usize, url: &str) -> String {
    format!("redirect limit exceeded after {max_redirects} redirects for {url}")
}
