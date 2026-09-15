"""
QUIC Initial Packet Cryptography Tool — Solution Implementation.

Supports QUIC v1 (RFC 9001) and QUIC v2 (RFC 9369) Initial packet
key derivation, header protection removal, AEAD decryption, and frame parsing.

"""

import hmac
import hashlib
import struct

from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


# ── Version-specific constants ────────────────────────────────────────────

_VERSION_PARAMS = {
    0x00000001: {  # QUIC v1
        "salt": bytes.fromhex("38762cf7f55934b34d179ae6a4c80cadccbb7f0a"),
        "key_label": b"quic key",
        "iv_label": b"quic iv",
        "hp_label": b"quic hp",
    },
    0x6B3343CF: {  # QUIC v2
        "salt": bytes.fromhex("0dede3def700a6db819381be6e269dcbf9bd2ed9"),
        "key_label": b"quicv2 key",
        "iv_label": b"quicv2 iv",
        "hp_label": b"quicv2 hp",
    },
}


# ── TLS 1.3 HKDF helpers ─────────────────────────────────────────────────

def _hkdf_expand_label(secret: bytes, label: bytes, context: bytes, length: int) -> bytes:
    """
    TLS 1.3 HKDF-Expand-Label (RFC 8446 Section 7.1).

    HkdfLabel = uint16(length) || uint8(len("tls13 "+label)) || "tls13 "+label
                || uint8(len(context)) || context
    """
    full_label = b"tls13 " + label
    hkdf_label = struct.pack(">H", length)
    hkdf_label += bytes([len(full_label)]) + full_label
    hkdf_label += bytes([len(context)]) + context
    return HKDFExpand(
        algorithm=hashes.SHA256(),
        length=length,
        info=hkdf_label,
    ).derive(secret)


# ── Public API ────────────────────────────────────────────────────────────

def derive_initial_keys(dcid: bytes, version: int, perspective: str) -> dict:
    """
    Derive QUIC Initial AEAD keys from a Destination Connection ID.

    Returns dict with "key" (16 B), "iv" (12 B), "hp" (16 B).
    """
    vp = _VERSION_PARAMS.get(version)
    if vp is None:
        raise ValueError(f"Unsupported QUIC version: 0x{version:08x}")

    # HKDF-Extract: initial_secret = HMAC-SHA256(salt, dcid)
    initial_secret = hmac.new(vp["salt"], dcid, hashlib.sha256).digest()

    # Per-perspective secret
    per_label = b"client in" if perspective == "client" else b"server in"
    secret = _hkdf_expand_label(initial_secret, per_label, b"", 32)

    return {
        "key": _hkdf_expand_label(secret, vp["key_label"], b"", 16),
        "iv": _hkdf_expand_label(secret, vp["iv_label"], b"", 12),
        "hp": _hkdf_expand_label(secret, vp["hp_label"], b"", 16),
    }


def parse_quic_varint(data: bytes, offset: int) -> tuple:
    """
    Parse a QUIC variable-length integer (RFC 9000 Section 16).
    Returns (value, bytes_consumed).
    """
    first = data[offset]
    prefix = first >> 6

    if prefix == 0:
        return first & 0x3F, 1
    elif prefix == 1:
        return int.from_bytes(data[offset : offset + 2], "big") & 0x3FFF, 2
    elif prefix == 2:
        return int.from_bytes(data[offset : offset + 4], "big") & 0x3FFFFFFF, 4
    else:
        return int.from_bytes(data[offset : offset + 8], "big") & 0x3FFFFFFFFFFFFFFF, 8


def remove_header_protection(packet: bytes, hp_key: bytes) -> tuple:
    """
    Remove header protection from a QUIC long-header Initial packet.

    Returns (unprotected_header, packet_number, pn_length, payload_start_offset).
    """
    first_byte = packet[0]

    # ── Parse header fields to locate the Packet Number field ──
    # (pn_length is unknown until after unmasking the first byte)
    off = 1          # skip first byte
    off += 4         # skip version
    dcid_len = packet[off]
    off += 1 + dcid_len
    scid_len = packet[off]
    off += 1 + scid_len

    # Token length (varint) + token bytes
    token_len, vlen = parse_quic_varint(packet, off)
    off += vlen + token_len

    # Payload length (varint) — value not needed for unprotection
    _, vlen = parse_quic_varint(packet, off)
    off += vlen

    pn_offset = off

    # ── Compute mask ──
    sample = packet[pn_offset + 4 : pn_offset + 4 + 16]
    cipher = Cipher(algorithms.AES(hp_key), modes.ECB())
    mask = cipher.encryptor().update(sample)

    # ── Unmask first byte (long header → lower 4 bits) ──
    unprotected_first = first_byte ^ (mask[0] & 0x0F)
    pn_length = (unprotected_first & 0x03) + 1

    # ── Unmask packet-number bytes ──
    pn_bytes = bytearray(packet[pn_offset : pn_offset + pn_length])
    for i in range(pn_length):
        pn_bytes[i] ^= mask[1 + i]

    packet_number = int.from_bytes(pn_bytes, "big")

    # ── Reconstruct the unprotected header ──
    unprotected_header = (
        bytes([unprotected_first]) + packet[1:pn_offset] + bytes(pn_bytes)
    )
    payload_start = pn_offset + pn_length

    return unprotected_header, packet_number, pn_length, payload_start


def decrypt_payload(
    encrypted_payload: bytes,
    packet_number: int,
    key: bytes,
    iv: bytes,
    header: bytes,
) -> bytes:
    """
    Decrypt a QUIC packet payload using AES-128-GCM.
    `header` is the unprotected header bytes (used as AAD).
    """
    nonce = bytearray(iv)
    pn_padded = packet_number.to_bytes(len(nonce), "big")
    for i in range(len(nonce)):
        nonce[i] ^= pn_padded[i]

    return AESGCM(key).decrypt(bytes(nonce), encrypted_payload, header)


def parse_frames(payload: bytes) -> list:
    """
    Parse QUIC frames from a decrypted payload.

    Supported types: PADDING (0x00), PING (0x01), ACK (0x02/0x03), CRYPTO (0x06).
    """
    frames = []
    offset = 0

    while offset < len(payload):
        ft, consumed = parse_quic_varint(payload, offset)
        offset += consumed

        if ft == 0x00:
            frames.append({"type": "PADDING"})

        elif ft == 0x01:
            frames.append({"type": "PING"})

        elif ft in (0x02, 0x03):
            largest, c = parse_quic_varint(payload, offset); offset += c
            delay, c = parse_quic_varint(payload, offset); offset += c
            range_count, c = parse_quic_varint(payload, offset); offset += c
            first_range, c = parse_quic_varint(payload, offset); offset += c
            for _ in range(range_count):
                gap, c = parse_quic_varint(payload, offset); offset += c
                ack_rng, c = parse_quic_varint(payload, offset); offset += c
            if ft == 0x03:  # ACK-ECN
                for _ in range(3):
                    _, c = parse_quic_varint(payload, offset); offset += c
            frames.append({"type": "ACK", "largest_ack": largest})

        elif ft == 0x06:
            crypto_off, c = parse_quic_varint(payload, offset); offset += c
            crypto_len, c = parse_quic_varint(payload, offset); offset += c
            data = payload[offset : offset + crypto_len]
            offset += crypto_len
            frames.append({
                "type": "CRYPTO",
                "offset": crypto_off,
                "length": crypto_len,
                "data": data,
            })

        elif ft in (0x1C, 0x1D):
            error_code, c = parse_quic_varint(payload, offset); offset += c
            if ft == 0x1C:
                _, c = parse_quic_varint(payload, offset); offset += c
            reason_len, c = parse_quic_varint(payload, offset); offset += c
            offset += reason_len
            frames.append({"type": "CONNECTION_CLOSE", "error_code": error_code})

        else:
            frames.append({"type": f"UNKNOWN_{ft}"})
            break

    return frames
