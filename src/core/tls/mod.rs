#[cfg(test)]
mod tests;

use rustls::crypto::ring;
use rustls::pki_types::{pem::PemObject, CertificateDer};
use rustls::{ClientConfig, RootCertStore};

pub fn build_tls_config(ca_certificates: &[Vec<u8>]) -> Result<ClientConfig, String> {
    let mut roots = webpki_root_store();
    add_ca_certificates(&mut roots, ca_certificates)?;

    let provider = ring::default_provider();
    let builder = ClientConfig::builder_with_provider(provider.into())
        .with_safe_default_protocol_versions()
        .map_err(|err| format!("failed to configure TLS protocol versions: {err}"))?;

    Ok(builder.with_root_certificates(roots).with_no_client_auth())
}

fn webpki_root_store() -> RootCertStore {
    let mut roots = RootCertStore::empty();
    roots.extend(webpki_roots::TLS_SERVER_ROOTS.iter().cloned());
    roots
}

fn add_ca_certificates(
    roots: &mut RootCertStore,
    ca_certificates: &[Vec<u8>],
) -> Result<(), String> {
    for certificate in ca_certificates {
        let certificates = parse_ca_certificates(certificate)?;
        for certificate in certificates {
            roots
                .add(certificate)
                .map_err(|err| format!("failed to add CA certificate: {err}"))?;
        }
    }

    Ok(())
}

fn parse_ca_certificates(certificate: &[u8]) -> Result<Vec<CertificateDer<'static>>, String> {
    let mut certificates = Vec::new();
    for certificate in CertificateDer::pem_slice_iter(certificate) {
        certificates
            .push(certificate.map_err(|err| format!("failed to parse CA certificate PEM: {err}"))?);
    }
    if certificates.is_empty() {
        return Err("CA certificate PEM did not contain certificates".to_owned());
    }

    Ok(certificates)
}
