mod constants;
mod origin;
mod scheme;

use url::Url;

#[derive(Clone, Debug)]
pub struct HttpUrl {
    inner: Url,
}

impl HttpUrl {
    pub fn parse(url: &str) -> Result<Self, String> {
        let inner = Url::parse(url).map_err(|err| format!("URL is invalid: {err}"))?;
        if !scheme::is_supported(inner.scheme()) {
            return Err(constants::INVALID_SCHEME_ERROR.to_owned());
        }
        if inner.host_str().is_none() {
            return Err(constants::MISSING_HOST_ERROR.to_owned());
        }

        Ok(Self { inner })
    }

    pub fn as_str(&self) -> &str {
        self.inner.as_str()
    }

    pub fn scheme(&self) -> &str {
        self.inner.scheme()
    }

    pub fn host(&self) -> String {
        let host = self
            .inner
            .host_str()
            .expect(constants::VALIDATED_URL_HOST_EXPECTATION);
        host.strip_prefix('[')
            .and_then(|value| value.strip_suffix(']'))
            .unwrap_or(host)
            .to_owned()
    }

    pub fn port(&self) -> u16 {
        self.inner
            .port_or_known_default()
            .expect(constants::VALIDATED_URL_PORT_EXPECTATION)
    }

    pub fn path(&self) -> &str {
        self.inner.path()
    }

    pub fn query(&self) -> &str {
        self.inner.query().unwrap_or_default()
    }

    pub fn fragment(&self) -> &str {
        self.inner.fragment().unwrap_or_default()
    }

    pub(crate) fn is_origin_only(&self) -> bool {
        self.inner.username().is_empty()
            && self.inner.password().is_none()
            && matches!(self.inner.path(), "" | "/")
            && self.inner.query().is_none()
            && self.inner.fragment().is_none()
    }

    pub fn origin(&self) -> String {
        origin::format_origin(self.scheme(), &self.host(), self.port())
    }

    pub fn join(&self, location: &str) -> Result<Self, String> {
        let inner = self
            .inner
            .join(location)
            .map_err(|err| format!("URL is invalid: {err}"))?;
        Self::parse(inner.as_str())
    }

    pub fn is_same_origin(&self, other: &Self) -> bool {
        let left = origin::OriginRef::new(self.scheme(), self.inner.host_str(), self.port());
        let right = origin::OriginRef::new(other.scheme(), other.inner.host_str(), other.port());
        left.is_same(right)
    }
}

#[cfg(test)]
mod tests;
