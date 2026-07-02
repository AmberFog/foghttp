from ..messages import STREAMING_BODY_CHUNK_UNSUPPORTED


def body_chunk(content: object) -> bytes:
    if isinstance(content, bytes):
        return content
    if isinstance(content, bytearray):
        return bytes(content)
    if isinstance(content, memoryview):
        return content.tobytes()
    raise TypeError(STREAMING_BODY_CHUNK_UNSUPPORTED)
