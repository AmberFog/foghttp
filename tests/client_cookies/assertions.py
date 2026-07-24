__all__ = ("cookie_pairs", "request_cookie_pairs")

from collections.abc import Iterable

import foghttp


def cookie_pairs(values: Iterable[str]) -> set[str]:
    return {pair.strip() for value in values for pair in value.split(";") if pair.strip()}


def request_cookie_pairs(response: foghttp.Response | foghttp.StreamResponse) -> set[str]:
    return cookie_pairs(response.request.headers.get_list("cookie"))
