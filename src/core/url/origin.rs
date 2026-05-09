use super::scheme;

#[derive(Clone, Copy)]
pub(super) struct OriginRef<'a> {
    scheme: &'a str,
    host: Option<&'a str>,
    port: u16,
}

impl<'a> OriginRef<'a> {
    pub(super) fn new(scheme: &'a str, host: Option<&'a str>, port: u16) -> Self {
        Self { scheme, host, port }
    }

    pub(super) fn is_same(self, other: Self) -> bool {
        self.scheme == other.scheme && self.host == other.host && self.port == other.port
    }
}

pub(super) fn format_origin(scheme: &str, host: &str, port: u16) -> String {
    let mut netloc = host_netloc(host);
    if port != scheme::default_port(scheme) {
        netloc = format!("{netloc}:{port}");
    }
    format!("{scheme}://{netloc}")
}

fn host_netloc(host: &str) -> String {
    if host.contains(':') && !host.starts_with('[') {
        return format!("[{host}]");
    }
    host.to_owned()
}
