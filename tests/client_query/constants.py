__all__ = ("QUERY_PRESERVING_REDIRECT_PARAMS",)

import pytest

from foghttp.status_codes.redirect import (
    FOUND,
    MOVED_PERMANENTLY,
    PERMANENT_REDIRECT,
    TEMPORARY_REDIRECT,
)


QUERY_PRESERVING_REDIRECT_PARAMS = (
    pytest.param(MOVED_PERMANENTLY, id="301-moved-permanently"),
    pytest.param(FOUND, id="302-found"),
    pytest.param(TEMPORARY_REDIRECT, id="307-temporary-redirect"),
    pytest.param(PERMANENT_REDIRECT, id="308-permanent-redirect"),
)
