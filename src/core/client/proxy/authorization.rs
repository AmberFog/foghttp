use hyper::header::HeaderValue;

#[derive(Clone)]
pub(super) struct ProxyAuthorization(String);

impl ProxyAuthorization {
    pub(super) fn parse(value: &str) -> Result<Self, String> {
        let header_value = HeaderValue::from_str(value)
            .map_err(|_| "proxy authorization header is invalid".to_owned())?;
        header_value
            .to_str()
            .map_err(|_| "proxy authorization header is invalid".to_owned())?;
        Ok(Self(value.to_owned()))
    }

    pub(super) fn as_str(&self) -> &str {
        &self.0
    }
}
