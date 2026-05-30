__all__ = ("pytest_plugins",)


pytest_plugins = (
    "tests.support.async_http_server",
    "tests.support.sync_http_server",
)
