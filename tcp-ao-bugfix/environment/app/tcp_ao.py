#!/usr/bin/env python3
"""
TCP-AO (RFC 5925/5926/9235) KDF and MAC computation library.

Implements the Key Derivation Functions (KDF) and Message Authentication
Code (MAC) algorithms specified for TCP Authentication Option.

Supported algorithm pairs:
  - KDF_HMAC_SHA1 with HMAC-SHA-1-96
  - KDF_AES_128_CMAC with AES-128-CMAC-96
"""

import struct
import hmac
import hashlib
import socket

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


# =============================================================================
# AES-CMAC (RFC 4493)
# =============================================================================

def _aes128_encrypt(key, block):
    """Encrypt a single 16-byte block with AES-128 in ECB mode."""
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    encryptor = cipher.encryptor()
    return encryptor.update(block) + encryptor.finalize()


def _left_shift_one(data):
    """Left-shift a 16-byte string by 1 bit."""
    result = bytearray(16)
    overflow = 0
    for i in range(15, -1, -1):
        result[i] = ((data[i] << 1) | overflow) & 0xFF
        overflow = 1 if (data[i] & 0x80) else 0
    return bytes(result)


def _xor_bytes(a, b):
    """XOR two equal-length byte strings."""
    return bytes(x ^ y for x, y in zip(a, b))


def _cmac_generate_subkeys(key):
    """Generate CMAC subkeys K1, K2 from AES key per RFC 4493 Section 2.3."""
    CONST_ZERO = b'\x00' * 16
    CONST_RB = b'\x00' * 15 + b'\x87'

    L = _aes128_encrypt(key, CONST_ZERO)

    if (L[0] & 0x80) == 0:
        K1 = _left_shift_one(L)
    else:
        K1 = _xor_bytes(_left_shift_one(L), CONST_RB)

    if (K1[0] & 0x80) == 0:
        K2 = _left_shift_one(K1)
    else:
        K2 = _xor_bytes(_left_shift_one(K1), CONST_RB)

    return K1, K2


def aes_128_cmac(key, message):
    """Compute AES-128-CMAC per RFC 4493.

    Args:
        key: 16-byte AES key
        message: variable-length message bytes

    Returns:
        16-byte MAC value
    """
    assert len(key) == 16, f"AES-128-CMAC requires 16-byte key, got {len(key)}"
    K1, K2 = _cmac_generate_subkeys(key)

    n = max((len(message) + 15) // 16, 1)

    if len(message) == 0:
        flag = False
    else:
        flag = (len(message) % 16 == 0)

    if flag:
        M_last = _xor_bytes(message[(n - 1) * 16 : n * 16], K1)
    else:
        last_block = message[(n - 1) * 16:]
        padding_len = 16 - len(last_block)
        padded = last_block + b'\x80' + b'\x00' * (padding_len - 1)
        M_last = _xor_bytes(padded, K2)

    X = b'\x00' * 16
    for i in range(n - 1):
        Y = _xor_bytes(X, message[i * 16 : (i + 1) * 16])
        X = _aes128_encrypt(key, Y)

    Y = _xor_bytes(X, M_last)
    return _aes128_encrypt(key, Y)


# =============================================================================
# Key Derivation Functions (RFC 5926)
# =============================================================================

def kdf_hmac_sha1(master_key, context, output_length_bits=160):
    """KDF using HMAC-SHA1 per RFC 5926 Section 3.1.1.1.

    Derives traffic keys using NIST SP800-108 counter mode with
    HMAC-SHA1 as the PRF.

    Input block structure: i || Label || Context || Output_Length
    where i is a single-octet counter and Output_Length is in bits.
    """
    label = b"TCP-AO\x00"  # TCP-AO KDF label

    result = b""
    prf_output_bits = 160
    num_blocks = (output_length_bits + prf_output_bits - 1) // prf_output_bits

    for i in range(num_blocks):
        input_block = (
            struct.pack('B', i) +
            label +
            context +
            struct.pack('<H', output_length_bits)
        )
        block = hmac.new(master_key, input_block, hashlib.sha1).digest()
        result += block

    return result[:output_length_bits // 8]


def kdf_aes_128_cmac(master_key, context, output_length_bits=128):
    """KDF using AES-128-CMAC per RFC 5926 Section 3.1.1.2.

    Derives traffic keys using NIST SP800-108 counter mode with
    AES-128-CMAC as the PRF. Handles variable-length master keys
    by normalizing to 16 bytes for AES compatibility.
    """
    # Key normalization: AES-128-CMAC requires exactly 16-byte key
    if len(master_key) == 16:
        derived_key = master_key
    else:
        # Normalize variable-length key to 16 bytes
        derived_key = (master_key + b'\x00' * 16)[:16]

    label = b"TCP-AO\x00"  # TCP-AO KDF label

    result = b""
    prf_output_bits = 128
    num_blocks = (output_length_bits + prf_output_bits - 1) // prf_output_bits

    for i in range(num_blocks):
        input_block = (
            struct.pack('B', i) +
            label +
            context +
            struct.pack('<H', output_length_bits)
        )
        block = aes_128_cmac(derived_key, input_block)
        result += block

    return result[:output_length_bits // 8]


# =============================================================================
# Context Construction (RFC 5925 Section 5.2)
# =============================================================================

def build_context(src_addr, dst_addr, src_port, dst_port,
                  src_isn, dst_isn, ip_version):
    """Build the KDF context per RFC 5925 Section 5.2.

    Context = SrcAddr || DstAddr || SrcPort || DstPort || SrcISN || DstISN

    For IPv4: 4+4+2+2+4+4 = 20 bytes
    For IPv6: 16+16+2+2+4+4 = 44 bytes
    """
    if ip_version == 4:
        addr_bytes = socket.inet_aton(src_addr) + socket.inet_aton(dst_addr)
    else:
        addr_bytes = (socket.inet_pton(socket.AF_INET6, src_addr) +
                      socket.inet_pton(socket.AF_INET6, dst_addr))

    return (addr_bytes +
            struct.pack('!HH', src_port, dst_port) +
            struct.pack('!II', src_isn, dst_isn))


def derive_traffic_key(master_key, kdf_alg, src_addr, dst_addr,
                       src_port, dst_port, src_isn, dst_isn, ip_version):
    """Derive a TCP-AO traffic key.

    Args:
        master_key: shared secret (bytes)
        kdf_alg: "HMAC-SHA1" or "AES-128-CMAC"
        src_addr: source IP address (string)
        dst_addr: destination IP address (string)
        src_port: source TCP port
        dst_port: destination TCP port
        src_isn: source Initial Sequence Number
        dst_isn: destination ISN (0 if unknown, e.g., for initial SYN)
        ip_version: 4 or 6

    Returns:
        Traffic key bytes (20 bytes for HMAC-SHA1, 16 bytes for AES-128-CMAC)
    """
    context = build_context(src_addr, dst_addr, src_port, dst_port,
                            src_isn, dst_isn, ip_version)

    if kdf_alg == "HMAC-SHA1":
        return kdf_hmac_sha1(master_key, context, 160)
    elif kdf_alg == "AES-128-CMAC":
        return kdf_aes_128_cmac(master_key, context, 128)
    else:
        raise ValueError(f"Unsupported KDF algorithm: {kdf_alg}")


# =============================================================================
# MAC Computation (RFC 5925 Section 5.1)
# =============================================================================

def _build_ipv4_pseudoheader(packet):
    """Build IPv4 TCP pseudoheader (12 bytes).

    Structure: SrcAddr(4) || DstAddr(4) || Zero(1) || Protocol(1) || TCPLen(2)
    """
    src_ip = packet[12:16]
    dst_ip = packet[16:20]
    protocol = packet[9]
    ip_header_len = (packet[0] & 0x0F) * 4
    total_len = struct.unpack('!H', packet[2:4])[0]
    tcp_length = total_len - ip_header_len

    pseudoheader = (src_ip + dst_ip +
                    b'\x00' + bytes([protocol]) +
                    struct.pack('!H', tcp_length))
    return pseudoheader, ip_header_len


def _build_ipv6_pseudoheader(packet):
    """Build IPv6 TCP pseudoheader (40 bytes).

    Structure: SrcAddr(16) || DstAddr(16) || UpperLayerLen(4) || Zero(3) || NextHdr(1)
    """
    src_ip = packet[8:24]
    dst_ip = packet[24:40]
    payload_length = struct.unpack('!H', packet[4:6])[0]
    next_header = packet[6]

    pseudoheader = (src_ip + dst_ip +
                    struct.pack('!I', payload_length) +
                    b'\x00\x00\x00' + bytes([next_header]))
    return pseudoheader, 40


def _find_tcp_ao_option(tcp_bytes, tcp_header_len):
    """Find TCP-AO option (kind=29) in TCP header options.

    Returns:
        (offset_from_tcp_start, option_length) or (None, None)
    """
    offset = 20  # Skip fixed TCP header
    while offset < tcp_header_len:
        kind = tcp_bytes[offset]
        if kind == 0:
            break
        if kind == 1:  # NOP
            offset += 1
            continue
        if offset + 1 >= tcp_header_len:
            break
        opt_len = tcp_bytes[offset + 1]
        if opt_len < 2:
            break
        if kind == 29:  # TCP-AO
            return offset, opt_len
        offset += opt_len
    return None, None


def compute_tcp_ao_mac(traffic_key, packet_bytes, sne, covers_options, mac_alg):
    """Compute TCP-AO MAC per RFC 5925 Section 5.1.

    The MAC is computed over:
      SNE(4) || IP_Pseudoheader || TCP_Header [with options if covered] || Payload

    Before computation, the TCP-AO MAC field is set to zero.

    Args:
        traffic_key: derived traffic key (bytes)
        packet_bytes: complete IP packet (bytes)
        sne: Sequence Number Extension (32-bit integer)
        covers_options: if True, TCP options are included in MAC input
        mac_alg: "HMAC-SHA-1-96" or "AES-128-CMAC-96"

    Returns:
        12-byte (96-bit) MAC value
    """
    packet = bytearray(packet_bytes)

    # Determine IP version from first nibble
    ip_version = (packet[0] >> 4) & 0x0F

    # Build IP pseudoheader
    if ip_version == 4:
        pseudoheader, ip_hdr_len = _build_ipv4_pseudoheader(packet)
    else:
        pseudoheader, ip_hdr_len = _build_ipv6_pseudoheader(packet)

    # Extract TCP segment as mutable copy
    tcp = bytearray(packet[ip_hdr_len:])
    tcp_header_len = ((tcp[12] >> 4) & 0x0F) * 4

    # Find TCP-AO option to zero its MAC field
    ao_offset, ao_len = _find_tcp_ao_option(tcp, tcp_header_len)
    if ao_offset is None:
        raise ValueError("TCP-AO option (kind=29) not found in TCP header")

    # Zero the MAC field within TCP-AO option
    # TCP-AO: Kind(1) | Length(1) | KeyID(1) | RNextKeyID(1) | MAC(variable)
    mac_field_offset = ao_offset + 4
    mac_field_len = ao_len - 4
    for idx in range(mac_field_offset, mac_field_offset + mac_field_len):
        tcp[idx] = 0x00

    # Construct MAC input message
    sne_bytes = struct.pack('!I', sne)

    if covers_options:
        tcp_header_bytes = bytes(tcp[:tcp_header_len])
    else:
        tcp_header_bytes = bytes(tcp[:20])

    tcp_payload = bytes(tcp[tcp_header_len:])

    message = sne_bytes + pseudoheader + tcp_header_bytes + tcp_payload

    # Compute MAC and truncate to 96 bits (12 bytes)
    if mac_alg == "HMAC-SHA-1-96":
        full_mac = hmac.new(traffic_key, message, hashlib.sha1).digest()
        return full_mac[:12]
    elif mac_alg == "AES-128-CMAC-96":
        full_mac = aes_128_cmac(traffic_key, message)
        return full_mac[:12]
    else:
        raise ValueError(f"Unsupported MAC algorithm: {mac_alg}")
