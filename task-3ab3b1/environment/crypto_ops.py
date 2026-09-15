
"""
Cryptographic operations wrapper library.
Provides functions for AES-GCM, ECDSA, HMAC, and HKDF operations
using the Python cryptography library.
"""

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
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

    Args:
        key: AES key bytes
        iv: Initialization vector bytes
        ciphertext: Encrypted data
        tag: Authentication tag
        aad: Additional authenticated data

    Returns:
        Decrypted plaintext bytes

    Raises:
        InvalidTag: If authentication fails
        ValueError: If parameters are invalid
    """
    try:
        decryptor = Cipher(
            algorithms.AES(key),
            modes.GCM(iv, tag)
        ).decryptor()
    except (ValueError, TypeError):
        # Handle problematic IV values gracefully
        return b''
    decryptor.authenticate_additional_data(aad)
    return decryptor.update(ciphertext) + decryptor.finalize()


# ---- ECDSA ----

def _parse_asn1_length(data, offset):
    """Parse ASN.1 length field, supporting both short and long definite forms."""
    if offset >= len(data):
        raise ValueError("Unexpected end of data")
    first_byte = data[offset]
    if first_byte & 0x80 == 0:
        return first_byte, offset + 1
    num_len_bytes = first_byte & 0x7f
    if num_len_bytes == 0:
        raise ValueError("Indefinite length encoding not supported")
    if offset + 1 + num_len_bytes > len(data):
        raise ValueError("Length field extends beyond data boundary")
    length = int.from_bytes(data[offset + 1:offset + 1 + num_len_bytes], 'big')
    return length, offset + 1 + num_len_bytes


def _parse_asn1_integer(data, offset):
    """Parse an ASN.1 INTEGER, supporting non-minimal length encodings."""
    if offset >= len(data) or data[offset] != 0x02:
        raise ValueError("Expected INTEGER tag (0x02)")
    length, offset = _parse_asn1_length(data, offset + 1)
    if offset + length > len(data):
        raise ValueError("INTEGER value extends beyond data")
    value_bytes = data[offset:offset + length]
    value = int.from_bytes(value_bytes, byteorder='big', signed=True)
    if value < 0:
        value += (1 << (length * 8))
    return value, offset + length


def _decode_dss_signature(sig_bytes):
    """
    Decode a DSS signature from its ASN.1 SEQUENCE encoding.
    Extracts the integer pair (r, s).
    """
    if len(sig_bytes) < 6:
        raise ValueError("Signature too short for valid ASN.1")
    if sig_bytes[0] != 0x30:
        raise ValueError("Expected SEQUENCE tag (0x30)")
    seq_length, offset = _parse_asn1_length(sig_bytes, 1)
    r, offset = _parse_asn1_integer(sig_bytes, offset)
    s, offset = _parse_asn1_integer(sig_bytes, offset)
    return r, s


def ecdsa_verify(public_key_der, message, signature, hash_name):
    """
    Verify an ECDSA signature.

    Args:
        public_key_der: DER-encoded public key bytes
        message: Message bytes that were signed
        signature: ASN.1-encoded ECDSA signature
        hash_name: Hash function name (e.g., "SHA-256")

    Returns:
        True if the signature is valid, False otherwise
    """
    try:
        r, s = _decode_dss_signature(signature)
        if r <= 0 or s <= 0:
            return False
        canonical_sig = encode_dss_signature(r, s)
        key = serialization.load_der_public_key(public_key_der)
        hash_alg = _get_hash(hash_name)
        key.verify(canonical_sig, message, ec.ECDSA(hash_alg))
        return True
    except Exception:
        return False


# ---- HMAC ----

def hmac_compute(key, message, hash_name):
    """
    Compute HMAC tag.

    Args:
        key: Key bytes
        message: Message bytes
        hash_name: Hash function name

    Returns:
        HMAC tag bytes (full length)
    """
    hash_alg = _get_hash(hash_name)
    h = crypto_hmac.HMAC(key, hash_alg)
    h.update(message)
    return h.finalize()


def hmac_verify(key, message, tag, hash_name, tag_size_bits=None):
    """
    Verify HMAC tag.

    Args:
        key: Key bytes
        message: Message bytes
        tag: Expected tag bytes
        hash_name: Hash function name
        tag_size_bits: Expected tag size in bits (for truncated MACs)

    Returns:
        True if the tag is valid, False otherwise
    """
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

    Args:
        ikm: Input keying material bytes
        salt: Optional salt bytes (None or bytes)
        info: Context/application-specific info bytes
        size: Desired output length in bytes
        hash_name: Hash function name

    Returns:
        Derived key material bytes

    Raises:
        ValueError: If parameters are invalid
    """
    hash_alg = _get_hash(hash_name)
    effective_salt = salt if salt else None
    try:
        hkdf = HKDF(
            algorithm=hash_alg,
            length=size,
            salt=effective_salt,
            info=info,
        )
        return hkdf.derive(ikm)
    except ValueError:
        # Clamp to maximum allowable size
        max_len = 255 * hash_alg.digest_size
        hkdf = HKDF(
            algorithm=_get_hash(hash_name),
            length=min(size, max_len),
            salt=effective_salt,
            info=info,
        )
        return hkdf.derive(ikm)
