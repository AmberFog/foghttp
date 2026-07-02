from ..messages import MULTIPART_FILE_FACTORY_MIX_UNSUPPORTED
from ..types import RequestData
from .fields import multipart_fields
from .file_parts import multipart_files
from .models import MultipartPayload


def multipart_payload(
    *,
    boundary: str,
    data: RequestData,
    files: object,
) -> MultipartPayload:
    payload = MultipartPayload(
        boundary=boundary,
        fields=multipart_fields(data),
        files=multipart_files(files),
    )
    _validate_file_factory_mix(payload)
    return payload


def _validate_file_factory_mix(payload: MultipartPayload) -> None:
    if payload.has_file_factories and not payload.replayable:
        raise TypeError(MULTIPART_FILE_FACTORY_MIX_UNSUPPORTED)
