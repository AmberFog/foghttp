__all__ = ("AuthHeaderProvenance",)

from dataclasses import dataclass, field

from .headers import Headers


@dataclass(repr=False, slots=True)
class AuthHeaderProvenance:
    baseline_names: frozenset[str]
    request_owned_names: frozenset[str]
    _replacement_names: set[str] = field(default_factory=set, init=False, repr=False)
    _tracked_headers: Headers | None = field(default=None, init=False, repr=False)
    _tracked_version: int = field(default=0, init=False, repr=False)

    @classmethod
    def capture(
        cls,
        headers: Headers,
        *,
        body_checkpoint: int,
        request_owned_names: frozenset[str],
    ) -> "AuthHeaderProvenance":
        return cls(
            baseline_names=_header_names(headers),
            request_owned_names=(
                request_owned_names | headers._mutations_after(body_checkpoint)  # noqa: SLF001
            ),
        )

    def overrides(self, headers: Headers) -> tuple[tuple[str, ...], tuple[str, ...]]:
        current_names = _header_names(headers)
        if headers is not self._tracked_headers:
            return (
                tuple(sorted(current_names)),
                tuple(sorted(self.baseline_names - current_names)),
            )
        changed = (
            self._replacement_names | headers._mutations_after(self._tracked_version)  # noqa: SLF001
        )
        caller_owned = (self.request_owned_names | changed) & current_names
        return (
            tuple(sorted(caller_owned)),
            tuple(sorted(changed - current_names)),
        )

    def track(self, headers: Headers) -> None:
        self._tracked_headers = headers
        self._tracked_version = headers._mutation_checkpoint()  # noqa: SLF001

    def replace(self, headers: Headers) -> None:
        if headers is self._tracked_headers:
            return
        current_names = _header_names(headers)
        self._replacement_names.update(self.baseline_names)
        self._replacement_names.update(current_names)
        self.track(headers)


def _header_names(headers: Headers) -> frozenset[str]:
    return frozenset(name.lower() for name in headers)
