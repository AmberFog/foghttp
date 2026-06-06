__all__ = ("basic_proxy_authorization",)

from base64 import b64encode

from .models import ProxyUrl


def basic_proxy_authorization(proxy: ProxyUrl | None) -> str | None:
    if proxy is None or proxy.credentials is None:
        return None

    password = "" if proxy.credentials.password is None else proxy.credentials.password
    credentials = (proxy.credentials.username, password)
    token = ":".join(credentials).encode()
    encoded_credentials = b64encode(token).decode("ascii")
    authorization_parts = ("Basic", encoded_credentials)
    return " ".join(authorization_parts)
