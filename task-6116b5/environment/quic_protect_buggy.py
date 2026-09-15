"""QUIC Packet Protection Library
Implements packet protection per RFC 9001 and RFC 9369.
"""

import hmac
import hashlib
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305


# QUIC v1 Initial salt (RFC 9001 Section 5.2)
V1_INITIAL_SALT = bytes.fromhex("38762cf7f55934b34d179ae6a4c80cadccbb7f0a")

# QUIC v2 Initial salt (RFC 9369 Section 3.3.1)
V2_INITIAL_SALT = bytes.fromhex("0dede3def700dba6819381be6e269dcbf9bd2ed9")

V1_LABELS = {"key": "quic key", "iv": "quic iv", "hp": "quic hp", "ku": "quic ku"}
V2_LABELS = {"key": "quicv2 key", "iv": "quicv2 iv", "hp": "quicv2 hp", "ku": "quicv2 ku"}

V1_RETRY_KEY = bytes.fromhex("be0c690b9f66575a1d766b54e368c84e")
V1_RETRY_NONCE = bytes.fromhex("461599d35d632bf2239825bb")
V2_RETRY_KEY = bytes.fromhex("8fb4b01b56ac48e260fbcbcead7ccc92")
V2_RETRY_NONCE = bytes.fromhex("d86969bc2d7c6d9990efb04a")


def _hkdf_extract(salt, ikm):
    """HKDF-Extract (RFC 5869) using HMAC-SHA256."""
    return hmac.new(salt, ikm, hashlib.sha256).digest()


def _hkdf_expand(prk, info, length):
    """HKDF-Expand (RFC 5869) using HMAC-SHA256."""
    hash_len = 32
    n = (length + hash_len - 1) // hash_len
    okm = b""
    t = b""
    for i in range(1, n + 1):
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        okm += t
    return okm[:length]


def _hkdf_expand_label(secret, label, context, length):
    """TLS 1.3 HKDF-Expand-Label."""
    full_label = b"tls13 " + label.encode()
    hkdf_label = (
        struct.pack(">H", length)
        + bytes([len(full_label)]) + full_label
        + bytes([len(context)]) + context
    )
    return _hkdf_expand(secret, hkdf_label, length)


def derive_initial_keys(dcid, version):
    """Derive initial encryption keys from Destination Connection ID."""
    salt = V1_INITIAL_SALT if version == 1 else V2_INITIAL_SALT
    labels = V1_LABELS if version == 1 else V2_LABELS

    initial_secret = _hkdf_extract(salt, dcid)
    client_initial_secret = _hkdf_expand_label(initial_secret, "client in", b"", 32)
    server_initial_secret = _hkdf_expand_label(initial_secret, "server in", b"", 32)

    return {
        "initial_secret": initial_secret,
        "client_initial_secret": client_initial_secret,
        "server_initial_secret": server_initial_secret,
        "client_key": _hkdf_expand_label(client_initial_secret, labels["key"], b"", 16),
        "client_iv": _hkdf_expand_label(client_initial_secret, labels["iv"], b"", 12),
        "client_hp": _hkdf_expand_label(client_initial_secret, labels["hp"], b"", 16),
        "server_key": _hkdf_expand_label(server_initial_secret, labels["key"], b"", 16),
        "server_iv": _hkdf_expand_label(server_initial_secret, labels["iv"], b"", 12),
        "server_hp": _hkdf_expand_label(server_initial_secret, labels["hp"], b"", 16),
    }


def derive_keys_from_secret(secret, version, key_len):
    """Derive key, IV, HP key, and key update from a traffic secret."""
    labels = V1_LABELS if version == 1 else V2_LABELS
    return {
        "key": _hkdf_expand_label(secret, labels["key"], b"", key_len),
        "iv": _hkdf_expand_label(secret, labels["iv"], b"", 12),
        "hp": _hkdf_expand_label(secret, labels["hp"], b"", key_len),
        "ku": _hkdf_expand_label(secret, labels["ku"], b"", key_len),
    }


def protect_initial_packet(header, payload, key, iv, hp):
    """Apply AEAD encryption and header protection to an Initial packet."""
    pn_length = (header[0] & 0x03) + 1
    pn_offset = len(header) - pn_length
    pn = int.from_bytes(header[pn_offset:pn_offset + pn_length], "big")

    # Construct nonce: XOR IV with packet number
    nonce = bytearray(iv)
    pn_enc = pn.to_bytes(max((pn.bit_length() + 7) // 8, 1), "big")
    for i in range(len(pn_enc)):
        nonce[i] ^= pn_enc[i]
    nonce = bytes(nonce)

    # AEAD-AES-128-GCM encrypt
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, payload, header)

    # Assemble packet before header protection
    packet = bytearray(header) + bytearray(ciphertext)

    # Header protection sample
    sample_offset = pn_offset + 3
    sample = bytes(packet[sample_offset:sample_offset + 16])

    # AES-ECB mask generation
    cipher = Cipher(algorithms.AES(hp), modes.ECB())
    enc = cipher.encryptor()
    mask = enc.update(sample) + enc.finalize()

    # Apply header protection
    if packet[0] & 0x80:
        packet[0] ^= mask[0] & 0x0f
    else:
        packet[0] ^= mask[0] & 0x1f
    for i in range(pn_length):
        packet[pn_offset + i] ^= mask[1 + i]

    return bytes(packet)


def compute_retry_integrity_tag(odcid, retry_no_tag, version):
    """Compute the 16-byte Retry Integrity Tag."""
    if version == 1:
        rk, rn = V1_RETRY_KEY, V1_RETRY_NONCE
    else:
        rk, rn = V2_RETRY_KEY, V2_RETRY_NONCE

    pseudo_packet = odcid + retry_no_tag
    aesgcm = AESGCM(rk)
    return aesgcm.encrypt(rn, b"", pseudo_packet)


def protect_short_header_chacha20(header, payload, pn, key, iv, hp):
    """Protect a short header packet using ChaCha20-Poly1305."""
    pn_length = (header[0] & 0x03) + 1
    pn_offset = len(header) - pn_length

    # Construct nonce
    nonce = bytearray(iv)
    pn_padded = pn.to_bytes(len(iv), "big")
    for i in range(len(iv)):
        nonce[i] ^= pn_padded[i]
    nonce = bytes(nonce)

    # ChaCha20-Poly1305 AEAD encrypt
    aead = ChaCha20Poly1305(key)
    ciphertext = aead.encrypt(nonce, payload, header)

    # Assemble packet
    packet = bytearray(header) + bytearray(ciphertext)

    # Header protection sample
    sample_offset = pn_offset + 4
    sample = bytes(packet[sample_offset:sample_offset + 16])

    # ChaCha20 header protection mask
    counter = int.from_bytes(sample[0:4], "big")
    hp_nonce = sample[4:16]
    full_nonce = counter.to_bytes(4, "little") + hp_nonce
    cipher = Cipher(algorithms.ChaCha20(hp, full_nonce), mode=None)
    enc = cipher.encryptor()
    mask = enc.update(b"\x00" * 5)

    # Apply header protection (short header)
    packet[0] ^= mask[0] & 0x1f
    for i in range(pn_length):
        packet[pn_offset + i] ^= mask[1 + i]

    return bytes(packet)
