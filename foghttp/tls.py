__all__ = ("TLSConfig",)

from collections.abc import Sequence
from dataclasses import dataclass
from os import PathLike


CertificatePath = str | PathLike[str]
CertificatePathSource = CertificatePath | Sequence[CertificatePath]


@dataclass(frozen=True, init=False, slots=True)
class TLSConfig:
    ca_certificates: tuple[CertificatePath, ...]

    def __init__(self, ca_certificates: CertificatePathSource = ()) -> None:
        object.__setattr__(self, "ca_certificates", _normalize_ca_certificates(ca_certificates))


def _normalize_ca_certificates(ca_certificates: object) -> tuple[CertificatePath, ...]:
    if isinstance(ca_certificates, str | PathLike):
        return (ca_certificates,)
    if not isinstance(ca_certificates, Sequence):
        msg = "ca_certificates must be a filesystem path or a sequence of filesystem paths"
        raise TypeError(msg)

    certificates: list[CertificatePath] = []
    for certificate in ca_certificates:
        if not isinstance(certificate, str | PathLike):
            msg = "ca_certificates must contain filesystem paths"
            raise TypeError(msg)
        certificates.append(certificate)
    return tuple(certificates)
