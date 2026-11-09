import pytest

from foghttp import _foghttp


NATIVE_UPLOAD_FRAGMENT_SIZE = 65_536
REJECTED_SEND_ATTEMPTS = 16


@pytest.mark.parametrize("final", [False, True])
def test_atomic_nowait_rejects_oversized_chunks_without_closing_upload(*, final: bool) -> None:
    raw_body = _foghttp.RawUploadBody(
        None,
        lambda _body: None,
        replayable=False,
        ready_callback=None,
    )
    oversized = b"x" * (NATIVE_UPLOAD_FRAGMENT_SIZE + 1)
    send = raw_body.send_final_nowait if final else raw_body.send_nowait
    try:
        for _ in range(REJECTED_SEND_ATTEMPTS):
            assert send(oversized) is False
            assert raw_body.is_closed() is False
        assert raw_body.send_final_nowait(b"recovery") is True
        assert raw_body.is_closed() is True
    finally:
        raw_body.close()
