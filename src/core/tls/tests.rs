use super::{build_tls_config, webpki_root_store};

#[test]
fn webpki_root_store_is_not_empty() {
    let roots = webpki_root_store();

    assert!(!roots.roots.is_empty());
}

#[test]
fn empty_custom_ca_pem_is_rejected() {
    let result = build_tls_config(&[b"not a certificate".to_vec()], true);
    let Err(error) = result else {
        panic!("expected invalid CA PEM to fail");
    };

    assert_eq!(error, "CA certificate PEM did not contain certificates");
}

#[test]
fn custom_only_trust_store_requires_custom_ca() {
    let result = build_tls_config(&[], false);
    let Err(error) = result else {
        panic!("expected empty custom-only TLS trust store to fail");
    };

    assert_eq!(
        error,
        "TLS trust store is empty; enable WebPKI roots or provide CA certificates",
    );
}
