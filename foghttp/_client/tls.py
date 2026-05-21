__all__ = ("ca_certificate_bytes", "trust_webpki_roots")

from pathlib import Path

from ..tls import CertificatePath, TLSConfig


def ca_certificate_bytes(tls: TLSConfig | None) -> tuple[bytes, ...]:
    if tls is None:
        return ()
    return tuple(_read_ca_certificate(certificate) for certificate in tls.ca_certificates)


def trust_webpki_roots(tls: TLSConfig | None) -> bool:
    return True if tls is None else tls.trust_webpki_roots


def _read_ca_certificate(certificate: CertificatePath) -> bytes:
    path = Path(certificate)
    try:
        return path.read_bytes()
    except OSError as exc:
        msg = f"failed to read CA certificate {path}: {exc.strerror}"
        raise ValueError(msg) from exc
