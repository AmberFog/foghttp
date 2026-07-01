from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MultipartField:
    name: str
    content: bytes


@dataclass(frozen=True, slots=True)
class MultipartFile:
    name: str
    filename: str
    content: object
    content_type: str
    content_length: int | None
    replayable: bool
    async_source: bool
    source_factory: bool = False
    close_source: bool = False


@dataclass(frozen=True, slots=True)
class MultipartPayload:
    boundary: str
    fields: tuple[MultipartField, ...]
    files: tuple[MultipartFile, ...]

    @property
    def replayable(self) -> bool:
        return all(file.replayable for file in self.files)

    @property
    def async_source(self) -> bool:
        return any(file.async_source for file in self.files)

    @property
    def has_file_factories(self) -> bool:
        return any(file.source_factory for file in self.files)

    @property
    def has_streaming_files(self) -> bool:
        return any(not isinstance(file.content, bytes) for file in self.files)
