__all__ = ("TLSConfig",)

from collections.abc import Sequence
from dataclasses import dataclass
from os import PathLike


CertificatePath = str | PathLike[str]
CertificatePathSource = CertificatePath | Sequence[CertificatePath]


@dataclass(frozen=True, init=False, slots=True)
class TLSConfig:
    ca_certificates: tuple[CertificatePath, ...]
    trust_webpki_roots: bool

    def __init__(
        self,
        ca_certificates: CertificatePathSource = (),
        *,
        trust_webpki_roots: bool = True,
    ) -> None:
        certificates = _normalize_ca_certificates(ca_certificates)
        _validate_trust_boundary(certificates, trust_webpki_roots)
        object.__setattr__(self, "ca_certificates", certificates)
        object.__setattr__(self, "trust_webpki_roots", trust_webpki_roots)


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


def _validate_trust_boundary(
    ca_certificates: tuple[CertificatePath, ...],
    trust_webpki_roots: object,
) -> None:
    if not isinstance(trust_webpki_roots, bool):
        msg = "trust_webpki_roots must be a boolean"
        raise TypeError(msg)
    if not trust_webpki_roots and not ca_certificates:
        msg = "custom-only TLS trust requires at least one CA certificate"
        raise ValueError(msg)
