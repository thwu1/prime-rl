#!/usr/bin/env python3
"""Diagnose and fix bugs in the QUIC packet protection implementation,
then add the unprotect_initial_packet function."""

with open("/app/quic_protect.py", "r") as f:
    code = f.read()

# -----------------------------------------------------------------------
# Bug 1: V2 Initial salt has bytes 6-7 transposed (dba6 should be a6db)
# The correct salt from RFC 9369 Section 3.3.1 is:
#   0dede3def700a6db819381be6e269dcbf9bd2ed9
# -----------------------------------------------------------------------
assert "0dede3def700dba6" in code, "Bug 1 (V2 salt transposition) not found"
code = code.replace(
    "0dede3def700dba6819381be6e269dcbf9bd2ed9",
    "0dede3def700a6db819381be6e269dcbf9bd2ed9",
)

# -----------------------------------------------------------------------
# Bug 2: Nonce construction in protect_initial_packet XORs the packet
# number from the LEFT (index 0) instead of RIGHT-aligning it within
# an IV-length buffer. RFC 9001 Section 5.3: "The nonce, N, is formed
# by combining the packet protection IV with the packet number."
# The packet number must be zero-padded to IV length (right-aligned).
# -----------------------------------------------------------------------
BUGGY_NONCE = (
    '    pn_enc = pn.to_bytes(max((pn.bit_length() + 7) // 8, 1), "big")\n'
    "    for i in range(len(pn_enc)):\n"
    "        nonce[i] ^= pn_enc[i]"
)
FIXED_NONCE = (
    '    pn_padded = pn.to_bytes(len(iv), "big")\n'
    "    for i in range(len(iv)):\n"
    "        nonce[i] ^= pn_padded[i]"
)
assert BUGGY_NONCE in code, "Bug 2 (nonce left-alignment) not found"
code = code.replace(BUGGY_NONCE, FIXED_NONCE)

# -----------------------------------------------------------------------
# Bug 3: Header protection sample offset is pn_offset + 3 instead of
# pn_offset + 4. RFC 9001 Section 5.4.2: "the sample of ciphertext is
# taken starting from an offset of 4 bytes after the start of the
# Packet Number field."
# -----------------------------------------------------------------------
assert "    sample_offset = pn_offset + 3" in code, "Bug 3 (sample offset) not found"
code = code.replace(
    "    sample_offset = pn_offset + 3",
    "    sample_offset = pn_offset + 4",
)

# -----------------------------------------------------------------------
# Bug 4: Retry pseudo-packet is missing the 1-byte ODCID length prefix.
# RFC 9001 Section 5.8: "The Retry Pseudo-Packet is ... a single byte
# containing the ODCID length, the ODCID itself, the retry packet."
# -----------------------------------------------------------------------
assert "    pseudo_packet = odcid + retry_no_tag" in code, "Bug 4 (retry ODCID prefix) not found"
code = code.replace(
    "    pseudo_packet = odcid + retry_no_tag",
    "    pseudo_packet = bytes([len(odcid)]) + odcid + retry_no_tag",
)

# -----------------------------------------------------------------------
# Bug 5: ChaCha20 header protection extracts the counter from the sample
# as big-endian instead of little-endian. RFC 9001 Section 5.4.4:
# "counter = sample[0..3]" is a little-endian 32-bit integer.
# -----------------------------------------------------------------------
assert '    counter = int.from_bytes(sample[0:4], "big")' in code, \
    "Bug 5 (ChaCha20 counter endianness) not found"
code = code.replace(
    '    counter = int.from_bytes(sample[0:4], "big")',
    '    counter = int.from_bytes(sample[0:4], "little")',
)

# -----------------------------------------------------------------------
# Add QUIC varint decoder and unprotect_initial_packet function
# -----------------------------------------------------------------------
code += '''

def _decode_varint(data, offset):
    """Decode a QUIC variable-length integer (RFC 9000 Section 16)."""
    first = data[offset]
    prefix = first >> 6
    if prefix == 0:
        return first, 1
    elif prefix == 1:
        return int.from_bytes(
            bytes([first & 0x3f, data[offset + 1]]), "big"
        ), 2
    elif prefix == 2:
        return int.from_bytes(
            bytes([first & 0x3f]) + bytes(data[offset + 1:offset + 4]), "big"
        ), 4
    else:
        return int.from_bytes(
            bytes([first & 0x3f]) + bytes(data[offset + 1:offset + 8]), "big"
        ), 8


def unprotect_initial_packet(packet, key, iv, hp):
    """Remove header protection and decrypt an Initial packet.

    Returns (header, payload) where header is the unprotected long header
    (including the recovered packet number bytes) and payload is the
    decrypted plaintext.
    """
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    packet = bytearray(packet)

    # Parse the long header to find the packet number offset.
    # Header protection only masks the first byte (lower 4 bits) and the
    # PN bytes, so all other fields are readable from the protected packet.
    pos = 5  # skip header byte (1) + version (4)
    dcid_len = packet[pos]
    pos += 1 + dcid_len
    scid_len = packet[pos]
    pos += 1 + scid_len
    token_len, tl_size = _decode_varint(packet, pos)
    pos += tl_size + token_len
    _, pl_size = _decode_varint(packet, pos)
    pos += pl_size
    pn_offset = pos

    # Compute the header protection mask from the AES-ECB sample
    sample = bytes(packet[pn_offset + 4:pn_offset + 4 + 16])
    cipher = Cipher(algorithms.AES(hp), modes.ECB())
    enc = cipher.encryptor()
    mask = enc.update(sample) + enc.finalize()

    # Remove header protection from the first byte (long header: 4-bit mask)
    packet[0] ^= mask[0] & 0x0f
    pn_length = (packet[0] & 0x03) + 1

    # Unmask the packet number bytes
    for i in range(pn_length):
        packet[pn_offset + i] ^= mask[1 + i]

    # Recover packet number value and reconstruct the unprotected header
    pn = int.from_bytes(packet[pn_offset:pn_offset + pn_length], "big")
    header = bytes(packet[:pn_offset + pn_length])

    # Construct the AEAD nonce (IV XOR right-aligned packet number)
    nonce = bytearray(iv)
    pn_padded = pn.to_bytes(len(iv), "big")
    for i in range(len(iv)):
        nonce[i] ^= pn_padded[i]

    # AEAD-AES-128-GCM decrypt
    ciphertext = bytes(packet[pn_offset + pn_length:])
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(bytes(nonce), ciphertext, header)

    return (header, plaintext)
'''

with open("/app/quic_protect.py", "w") as f:
    f.write(code)

# Quick verification that the fixes produce correct V1 initial secret
import sys
sys.path.insert(0, "/app")
import importlib
import quic_protect
importlib.reload(quic_protect)

dcid = bytes.fromhex("8394c8f03e515708")
keys = quic_protect.derive_initial_keys(dcid, 1)
expected = bytes.fromhex(
    "7db5df06e7a69e432496adedb0085192"
    "3595221596ae2ae9fb8115c1e9ed0a44"
)
assert keys["initial_secret"] == expected, "V1 initial_secret mismatch after fix"

keys_v2 = quic_protect.derive_initial_keys(dcid, 2)
expected_v2 = bytes.fromhex(
    "2062e8b3cd8d52092614b8071d0aa1fb"
    "7c2e3ac193f78b280e72d8f5751f6aba"
)
assert keys_v2["initial_secret"] == expected_v2, "V2 initial_secret mismatch after fix"

print("All 5 bugs fixed and unprotect_initial_packet added. Verification passed.")
