from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MultipartPart:
    name: str
    content: bytes
    filename: str | None = None
    content_type: str | None = None
