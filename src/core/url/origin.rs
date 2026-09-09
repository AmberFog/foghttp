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
