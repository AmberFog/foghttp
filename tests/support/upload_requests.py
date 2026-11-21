from dataclasses import replace

from foghttp import AsyncClient, Client, Request
from foghttp._request_body import request_body
from foghttp.methods import POST
from foghttp.types import BinaryFile


def known_length_upload_request(
    client: Client | AsyncClient,
    url: str,
    content: BinaryFile,
    content_length: int,
) -> Request:
    request = client.build_request(POST, url, content=content)
    # Exercise transport framing independently of safe file-length inference.
    request._body = replace(request_body(request), content_length=content_length)  # noqa: SLF001
    return request
