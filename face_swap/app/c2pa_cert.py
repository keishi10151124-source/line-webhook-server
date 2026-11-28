"""Personal C2PA signing certificate (a local CA plus a signing certificate).

Viewers will say the signer is not on a trusted list. That is expected for personal use;
the credentials still record that the video was made by an AI model.
"""
import datetime
import os
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def name(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "face-swap personal")])


def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca = (x509.CertificateBuilder().subject_name(name("face-swap personal CA")).issuer_name(name("face-swap personal CA"))
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=3650))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
          .add_extension(x509.KeyUsage(True, False, False, False, False, True, True, False, False), True)
          .sign(ca_key, hashes.SHA256()))
    key = ec.generate_private_key(ec.SECP256R1())
    leaf = (x509.CertificateBuilder().subject_name(name("face-swap signer")).issuer_name(ca.subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=825))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
            .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, False, False), True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
            .sign(ca_key, hashes.SHA256()))
    pem = serialization.Encoding.PEM
    (out / "c2pa_chain.pem").write_bytes(leaf.public_bytes(pem) + ca.public_bytes(pem))
    key_path = out / "c2pa_key.pem"
    key_path.write_bytes(key.private_bytes(pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    os.chmod(key_path, 0o600)
    print(f"wrote {out / 'c2pa_chain.pem'} and {key_path}")




def ensure_cert(cfg) -> None:
    """Create the certificate on first start if the configured files are missing."""
    chain, key = Path(cfg.C2PA_CERT_CHAIN_PATH), Path(cfg.C2PA_PRIVATE_KEY_PATH)
    if chain.exists() and key.exists():
        return
    out = chain.parent
    try:
        out.mkdir(parents=True, exist_ok=True)
        main(str(out))
        if out / "c2pa_chain.pem" != chain:
            (out / "c2pa_chain.pem").rename(chain)
        if out / "c2pa_key.pem" != key:
            (out / "c2pa_key.pem").rename(key)
    except OSError:
        # read-only location (e.g. a secrets mount): fall back to a writable folder
        import tempfile
        out = Path(tempfile.gettempdir()) / "face_swap_c2pa"
        if not (out / "c2pa_chain.pem").exists():
            main(str(out))
        cfg.C2PA_CERT_CHAIN_PATH = str(out / "c2pa_chain.pem")
        cfg.C2PA_PRIVATE_KEY_PATH = str(out / "c2pa_key.pem")
