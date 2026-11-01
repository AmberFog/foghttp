from contextlib import closing

import pytest

from foghttp import _foghttp
from tests.client_options.raw_options import raw_client_options


@pytest.mark.parametrize(
    ("terminal_method", "terminal_args", "terminal_result"),
    [
        pytest.param("finish", (), None, id="finish"),
        pytest.param("send_final", (b"",), True, id="empty-final"),
        pytest.param("fail", ("provider failed",), None, id="fail"),
        pytest.param("fail_nowait", ("provider failed",), True, id="fail-nowait"),
    ],
)
def test_raw_terminal_owner_close_releases_queued_bytes_while_owner_remains_live(
    terminal_method: str,
    terminal_args: tuple[object, ...],
    *,
    terminal_result: bool | None,
) -> None:
    with (
        closing(
            _foghttp.RawClient(**raw_client_options(max_upload_buffer_bytes=4, max_total_upload_buffer_bytes=4)),
        ) as raw_client,
        closing(
            _foghttp.RawUploadBody(
                None,
                lambda _body: None,
                replayable=False,
                ready_callback=None,
                raw_client=raw_client,
            ),
        ) as body,
        closing(
            _foghttp.RawUploadBody(
                None,
                lambda _body: None,
                replayable=False,
                ready_callback=None,
                raw_client=raw_client,
            ),
        ) as recovery,
    ):
        assert body.send_nowait(b"data") is True
        assert getattr(body, terminal_method)(*terminal_args) is terminal_result
        assert body.is_closed() is True
        assert recovery.send_nowait(b"r") is False

        body.close()
        body.close()

        assert recovery.send_final_nowait(b"r") is True
        assert body.is_closed() is True
