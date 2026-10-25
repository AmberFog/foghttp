from contextlib import ExitStack, closing
import json
from typing import Any

import pytest

from foghttp import _foghttp
from foghttp._client.proxy import ProxyTransportPolicy
from foghttp._validation.numeric import MAX_NUMERIC_OPTION
from foghttp.methods import POST
from foghttp.status_codes.success import OK

from .raw_options import raw_client_options


UPLOAD_LIMIT_FIELDS = ("max_upload_buffer_bytes", "max_total_upload_buffer_bytes")
RAW_REQUEST_METHODS = ("request", "request_stream", "request_async", "request_stream_async")
PAYLOAD = b"data"
STREAM_CHUNK_GUARD = 256


@pytest.mark.parametrize("field_name", UPLOAD_LIMIT_FIELDS)
@pytest.mark.parametrize(
    "value",
    [
        pytest.param(0, id="zero"),
        pytest.param(None, id="none"),
        pytest.param(True, id="bool"),
        pytest.param(-1, id="negative"),
        pytest.param(MAX_NUMERIC_OPTION + 1, id="overflow"),
        pytest.param(1.5, id="float"),
    ],
)
def test_raw_client_rejects_nonpositive_or_unbounded_upload_limits(field_name: str, value: object) -> None:
    with pytest.raises(ValueError, match=rf"Limits\.{field_name} must be an integer between 1 and"):
        _foghttp.RawClient(**raw_client_options(**{field_name: value}))


@pytest.mark.parametrize("value", [1, MAX_NUMERIC_OPTION])
def test_raw_client_accepts_upload_limit_boundaries(value: int) -> None:
    with closing(
        _foghttp.RawClient(
            **raw_client_options(max_upload_buffer_bytes=value, max_total_upload_buffer_bytes=value),
        ),
    ) as raw_client:
        assert raw_client.stats().total_requests == 0


@pytest.mark.parametrize("request_method", RAW_REQUEST_METHODS)
@pytest.mark.parametrize("standalone", [False, True], ids=["foreign-client", "standalone"])
async def test_raw_request_rejects_foreign_upload_budget_before_callback_and_admission(
    request_method: str,
    *,
    standalone: bool,
) -> None:
    callbacks: list[_foghttp.RawUploadBody] = []
    with ExitStack() as stack:
        receiving = stack.enter_context(closing(_foghttp.RawClient(**raw_client_options())))
        owner = None if standalone else stack.enter_context(closing(_foghttp.RawClient(**raw_client_options())))
        body = stack.enter_context(
            closing(
                _foghttp.RawUploadBody(
                    len(PAYLOAD),
                    callbacks.append,
                    replayable=False,
                    ready_callback=None,
                    raw_client=owner,
                ),
            ),
        )
        assert body.send_nowait(PAYLOAD) is True
        options = _raw_upload_request_options(body, url="http://127.0.0.1:1")

        with pytest.raises(ValueError, match="must be constructed with its receiving raw_client"):
            await _invoke_raw_request(receiving, request_method, options)

        assert callbacks == []
        assert body.is_closed() is False
        stats = receiving.stats()
        assert stats.total_requests == 0
        assert stats.active_requests == 0
        assert stats.pending_requests == 0
        assert stats.connections_opened == 0


@pytest.mark.parametrize("request_method", RAW_REQUEST_METHODS)
async def test_raw_request_accepts_its_bound_upload_budget(
    sync_http_server: str,
    request_method: str,
) -> None:
    callbacks: list[_foghttp.RawUploadBody] = []

    def start_upload(attempt: _foghttp.RawUploadBody) -> None:
        callbacks.append(attempt)
        assert attempt.send_final(PAYLOAD) is True

    with (
        closing(_foghttp.RawClient(**raw_client_options())) as raw_client,
        closing(
            _foghttp.RawUploadBody(
                len(PAYLOAD),
                start_upload,
                replayable=False,
                ready_callback=None,
                raw_client=raw_client,
            ),
        ) as body,
    ):
        response = await _invoke_raw_request(
            raw_client,
            request_method,
            _raw_upload_request_options(body, url=sync_http_server),
        )
        assert response.status_code == OK
        if "stream" in request_method:
            chunks: list[bytes] = []
            with closing(response):
                for _chunk_index in range(STREAM_CHUNK_GUARD):
                    chunk = (
                        await response.next_chunk_async()
                        if request_method.endswith("_async")
                        else response.next_chunk()
                    )
                    if chunk is None:
                        break
                    chunks.append(chunk)
                else:
                    pytest.fail("raw upload echo did not terminate within its finite response guard")
            content = b"".join(chunks)
        else:
            content = response.content
        assert json.loads(content)["body"] == PAYLOAD.decode()
        assert len(callbacks) == 1
        assert body.is_closed() is True
        assert raw_client.stats().active_requests == 0
        assert raw_client.stats().pending_requests == 0


def test_raw_upload_constructor_rejects_closed_client() -> None:
    raw_client = _foghttp.RawClient(**raw_client_options())
    raw_client.close()

    with pytest.raises(_foghttp.FogHttpError, match="client is closed"):
        _foghttp.RawUploadBody(None, lambda _body: None, replayable=False, ready_callback=None, raw_client=raw_client)


def test_raw_client_close_rejects_further_sends_to_prefilled_bound_upload() -> None:
    raw_client = _foghttp.RawClient(**raw_client_options())
    callbacks: list[_foghttp.RawUploadBody] = []
    try:
        with closing(
            _foghttp.RawUploadBody(
                None,
                callbacks.append,
                replayable=False,
                ready_callback=None,
                raw_client=raw_client,
            ),
        ) as body:
            assert body.send_nowait(PAYLOAD) is True
            assert body.is_closed() is False

            raw_client.close()

            assert body.is_closed() is True
            assert body.send_nowait(PAYLOAD) is False
            assert body.send_part_nowait(PAYLOAD, 0) == 0
            assert body.send_nowait(b"") is False
            assert callbacks == []
            raw_client.close()
    finally:
        raw_client.close()


async def _invoke_raw_request(
    raw_client: _foghttp.RawClient,
    request_method: str,
    options: dict[str, object],
) -> Any:
    response = getattr(raw_client, request_method)(**options)
    return await response if request_method.endswith("_async") else response


def _raw_upload_request_options(body: _foghttp.RawUploadBody, *, url: str) -> dict[str, object]:
    return {
        "method": POST,
        "url": url,
        "headers": [("content-length", str(len(PAYLOAD)))],
        "auth_override_headers": None,
        "auth_removed_headers": [],
        "extensions": None,
        "body": None,
        "body_stream": body,
        "body_replayable": False,
        "use_proxy_transport": False,
        "proxy_policy": ProxyTransportPolicy.DIRECT.value,
        "pool_timeout": 1.0,
        "read_timeout": 1.0,
        "write_timeout": 1.0,
        "total_timeout": 2.0,
    }
