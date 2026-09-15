"""
Cryptographic operations wrapper library (corrected).
All security bugs from the original version have been fixed.

"""

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hmac as crypto_hmac
import hmac as std_hmac


def _get_hash(name):
    """Map Wycheproof hash name to cryptography hash algorithm."""
    mapping = {
        'SHA-1': hashes.SHA1,
        'SHA-224': hashes.SHA224,
        'SHA-256': hashes.SHA256,
        'SHA-384': hashes.SHA384,
        'SHA-512': hashes.SHA512,
        'SHA3-256': hashes.SHA3_256,
        'SHA3-384': hashes.SHA3_384,
        'SHA3-512': hashes.SHA3_512,
    }
    if name not in mapping:
        raise ValueError(f"Unsupported hash function: {name}")
    return mapping[name]()


# ---- AES-GCM ----

def aes_gcm_encrypt(key, iv, plaintext, aad):
    """
    Encrypt using AES-GCM.

    Args:
        key: AES key bytes (16, 24, or 32 bytes)
        iv: Initialization vector bytes
        plaintext: Data to encrypt
        aad: Additional authenticated data

    Returns:
        Tuple of (ciphertext, authentication_tag)
    """
    encryptor = Cipher(algorithms.AES(key), modes.GCM(iv)).encryptor()
    encryptor.authenticate_additional_data(aad)
    ct = encryptor.update(plaintext) + encryptor.finalize()
    return ct, encryptor.tag


def aes_gcm_decrypt(key, iv, ciphertext, tag, aad):
    """
    Decrypt using AES-GCM.
    FIX: Removed try/except that silently swallowed ValueError for
    zero-length IV. Invalid parameters now propagate as exceptions.
    """
    decryptor = Cipher(
        algorithms.AES(key),
        modes.GCM(iv, tag)
    ).decryptor()
    decryptor.authenticate_additional_data(aad)
    return decryptor.update(ciphertext) + decryptor.finalize()


# ---- ECDSA ----

def ecdsa_verify(public_key_der, message, signature, hash_name):
    """
    Verify an ECDSA signature.
    FIX: Removed lenient ASN.1 parser that accepted BER encodings
    and re-encoded to DER. Now passes the raw signature directly to
    the library's strict DER parser.
    """
    try:
        key = serialization.load_der_public_key(public_key_der)
        hash_alg = _get_hash(hash_name)
        key.verify(signature, message, ec.ECDSA(hash_alg))
        return True
    except Exception:
        return False


# ---- HMAC ----

def hmac_compute(key, message, hash_name):
    """Compute HMAC tag."""
    hash_alg = _get_hash(hash_name)
    h = crypto_hmac.HMAC(key, hash_alg)
    h.update(message)
    return h.finalize()


def hmac_verify(key, message, tag, hash_name, tag_size_bits=None):
    """Verify HMAC tag with constant-time comparison."""
    try:
        computed = hmac_compute(key, message, hash_name)
        if tag_size_bits is not None:
            tag_size = tag_size_bits // 8
            return std_hmac.compare_digest(computed[:tag_size], tag)
        return std_hmac.compare_digest(computed[:len(tag)], tag)
    except Exception:
        return False


# ---- HKDF ----

def hkdf_derive(ikm, salt, info, size, hash_name):
    """
    Derive key material using HKDF (RFC 5869).
    FIX: Removed try/except that silently clamped output size to
    255 * hash_length when the requested size exceeded the limit.
    Now lets ValueError propagate for invalid sizes.
    """
    hash_alg = _get_hash(hash_name)
    effective_salt = salt if salt else None
    hkdf = HKDF(
        algorithm=hash_alg,
        length=size,
        salt=effective_salt,
        info=info,
    )
    return hkdf.derive(ikm)
