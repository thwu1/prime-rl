#!/usr/bin/env python3
"""
TCP-AO (RFC 5925/5926) Traffic Key Derivation and MAC Computation.

Computes traffic keys via KDF and MACs for TCP Authentication Option
segments, intended for validation against RFC 9235 test vectors.
"""

import hmac
import hashlib
import struct
import json
import sys
import ipaddress


# ---------------------------------------------------------------------------
# AES-CMAC  (RFC 4493)
# ---------------------------------------------------------------------------

def _aes_ecb(key, block):
    from Crypto.Cipher import AES
    return AES.new(key, AES.MODE_ECB).encrypt(block)


def _xor(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


def _shl1(b):
    out = bytearray(16)
    carry = 0
    for i in range(15, -1, -1):
        out[i] = ((b[i] << 1) | carry) & 0xff
        carry = (b[i] >> 7) & 1
    return bytes(out)


def _cmac_subkeys(key):
    RB = b'\x00' * 15 + b'\x87'
    L = _aes_ecb(key, b'\x00' * 16)
    K1 = _shl1(L)
    if L[0] & 0x80:
        K1 = _xor(K1, RB)
    K2 = _shl1(K1)
    if K1[0] & 0x80:
        K2 = _xor(K2, RB)
    return K1, K2


def aes_cmac(key, msg):
    """Compute AES-128-CMAC (RFC 4493)."""
    assert len(key) == 16, f"key must be 16 bytes, got {len(key)}"
    K1, K2 = _cmac_subkeys(key)
    n = max(1, (len(msg) + 15) // 16)
    complete = len(msg) > 0 and len(msg) % 16 == 0
    if complete:
        last = _xor(msg[-16:], K1)
    else:
        tail = msg[(n - 1) * 16:]
        pad = tail + b'\x80' + b'\x00' * (15 - len(tail))
        last = _xor(pad, K2)
    X = b'\x00' * 16
    for i in range(n - 1):
        X = _aes_ecb(key, _xor(X, msg[i * 16:(i + 1) * 16]))
    return _aes_ecb(key, _xor(X, last))


# ---------------------------------------------------------------------------
# Key Derivation Functions  (RFC 5926 Section 3.1.1)
# ---------------------------------------------------------------------------

def kdf_hmac_sha1(master_key, context, output_length_bits):
    """KDF_HMAC_SHA1: counter-mode KDF using HMAC-SHA-1 as PRF.

    Input block per iteration:  ( i || Label || Context || Output_Length )
    PRF output: 160 bits per block.
    """
    label = b"TCP-AO\x00"
    out_len = struct.pack("<H", output_length_bits)

    result = b""
    blocks = (output_length_bits + 159) // 160
    for i in range(blocks):
        data = struct.pack("B", i) + label + context + out_len
        result += hmac.new(master_key, data, hashlib.sha1).digest()
    return result[:output_length_bits // 8]


def kdf_aes_128_cmac(master_key, context, output_length_bits):
    """KDF_AES_128_CMAC: counter-mode KDF using AES-CMAC-PRF-128.

    For variable-length master keys the key is normalized to 16 bytes
    before use as the AES-CMAC key (RFC 5926 Section 3.1.1.2).
    """
    label = b"TCP-AO\x00"
    out_len = struct.pack("<H", output_length_bits)

    # Normalize master key to 16 bytes for AES-CMAC
    k = master_key.ljust(16, b'\x00')[:16]

    result = b""
    blocks = (output_length_bits + 127) // 128
    for i in range(blocks):
        data = struct.pack("B", i) + label + context + out_len
        result += aes_cmac(k, data)
    return result[:output_length_bits // 8]


# ---------------------------------------------------------------------------
# KDF Context  (RFC 5925 Section 5.2, Figures 7/8)
# ---------------------------------------------------------------------------

def build_context(src_addr, dst_addr, src_port, dst_port, src_isn, dst_isn):
    """Construct the KDF context byte string.

    Layout: SrcAddr || DstAddr || SrcPort || DstPort || SrcISN || DstISN
    """
    return (src_addr + dst_addr
            + struct.pack("!H", src_port) + struct.pack("!H", dst_port)
            + struct.pack("!I", src_isn) + struct.pack("!I", dst_isn))


def derive_traffic_key(kdf_alg, master_key,
                       src_addr, dst_addr, src_port, dst_port,
                       src_isn, dst_isn):
    """Derive a single traffic key using the given KDF algorithm."""
    ctx = build_context(src_addr, dst_addr, src_port, dst_port,
                        src_isn, dst_isn)
    if kdf_alg == "HMAC-SHA1":
        return kdf_hmac_sha1(master_key, ctx, 160)
    elif kdf_alg == "AES-128-CMAC":
        return kdf_aes_128_cmac(master_key, ctx, 128)
    raise ValueError(f"Unknown KDF algorithm: {kdf_alg}")


# ---------------------------------------------------------------------------
# MAC input construction  (RFC 5925 Section 5.1)
# ---------------------------------------------------------------------------

def _find_ao_option(tcp, hdr_len):
    """Locate TCP-AO option (kind 29). Returns (offset, opt_len) or (None, None)."""
    pos = 20
    while pos < hdr_len:
        kind = tcp[pos]
        if kind == 0:
            break
        if kind == 1:
            pos += 1
            continue
        opt_len = tcp[pos + 1]
        if kind == 29:
            return pos, opt_len
        pos += opt_len
    return None, None


def build_mac_input(sne, packet, covers_options):
    """Assemble the byte string fed to the MAC function.

    MAC_input = SNE(4) || Pseudoheader || TCP_header* || TCP_payload

    * For "covers options" the full TCP header (including options) is used;
      for "omits options" the fixed 20-byte TCP header plus the TCP-AO
      option are included (all other options omitted per RFC 5925 Sec 5.1).
      In both cases, the TCP checksum and the MAC field inside the TCP-AO
      option are zeroed before the MAC is computed.
    """
    pkt = bytearray(packet)
    ver = (pkt[0] >> 4) & 0xf

    if ver == 4:
        ihl = (pkt[0] & 0xf) * 4
        total = struct.unpack("!H", pkt[2:4])[0]
        src_ip = bytes(pkt[12:16])
        dst_ip = bytes(pkt[16:20])
        tcp_off = ihl
        tcp_len = total - ihl
        pseudo = src_ip + dst_ip + b'\x00\x06' + struct.pack("!H", tcp_len)
    else:  # IPv6
        pld = struct.unpack("!H", pkt[4:6])[0]
        src_ip = bytes(pkt[8:24])
        dst_ip = bytes(pkt[24:40])
        tcp_off = 40
        tcp_len = pld
        pseudo = (src_ip + dst_ip
                  + struct.pack("!I", tcp_len)
                  + b'\x00\x00\x00\x06')

    tcp = bytearray(pkt[tcp_off:tcp_off + tcp_len])
    tcp_hdr_len = ((tcp[12] >> 4) & 0xf) * 4

    # Zero the TCP checksum field before MAC computation
    # tcp[16:18] = b'\x00\x00'

    # Zero MAC bytes inside TCP-AO option
    ao_off, ao_len = _find_ao_option(tcp, tcp_hdr_len)
    if ao_off is not None:
        mac_start = ao_off + 4          # skip kind, len, keyid, rnextkeyid
        mac_sz = ao_len - 4
        tcp[mac_start:mac_start + mac_sz] = b'\x00' * mac_sz

    sne_bytes = struct.pack("!I", sne)

    if covers_options:
        hdr = bytes(tcp[:tcp_hdr_len])
    else:
        # Omit all TCP options EXCEPT TCP-AO (RFC 5925 Section 5.1)
        hdr = bytes(tcp[:20])
        if ao_off is not None:
            hdr += bytes(tcp[ao_off:ao_off + ao_len])

    payload = bytes(tcp[tcp_hdr_len:])
    return sne_bytes + pseudo + hdr + payload


# ---------------------------------------------------------------------------
# MAC computation  (RFC 5926 Section 3.2)
# ---------------------------------------------------------------------------

def compute_mac(mac_alg, traffic_key, mac_input):
    """Compute the 96-bit (12-byte) truncated MAC."""
    if mac_alg == "HMAC-SHA-1-96":
        return hmac.new(traffic_key, mac_input, hashlib.sha1).digest()[:12]
    elif mac_alg == "AES-128-CMAC-96":
        return aes_cmac(traffic_key, mac_input)[:12]
    raise ValueError(f"Unknown MAC algorithm: {mac_alg}")


# ---------------------------------------------------------------------------
# Test-vector helpers
# ---------------------------------------------------------------------------

def _resolve(ip_str, ver):
    if ver == 4:
        return ipaddress.IPv4Address(ip_str).packed
    return ipaddress.IPv6Address(ip_str).packed


def _key_params(tv):
    """Return (src_addr, dst_addr, src_port, dst_port, src_isn, dst_isn)
    for traffic-key derivation based on key_type."""
    ca = _resolve(tv["client_ip"], tv["ip_version"])
    sa = _resolve(tv["server_ip"], tv["ip_version"])
    cp = tv["client_port"]
    sp = tv["server_port"]
    ci = int(tv["client_isn"], 16) if tv["client_isn"] else 0
    si = int(tv["server_isn"], 16) if tv["server_isn"] else 0

    kt = tv["key_type"]
    if kt == "send_syn":
        # Client sends SYN (SYN=1, ACK=0): dest ISN unknown -> 0
        return ca, sa, cp, sp, ci, 0
    elif kt == "receive_syn":
        # Server sends SYN-ACK: both ISNs known (SYN-ACK is not a
        # pure SYN segment per RFC 5925 Sec 5.2)
        return sa, ca, sp, cp, si, ci
    elif kt == "send_other":
        return ca, sa, cp, sp, ci, si
    elif kt == "receive_other":
        return sa, ca, sp, cp, si, ci
    raise ValueError(f"Unknown key_type: {kt}")


def verify(tv):
    """Verify a single test vector.

    Returns (key_ok, mac_ok, computed_key_hex, computed_mac_hex).
    """
    mk = tv["master_key_ascii"].encode("ascii")
    src, dst, sp, dp, si, di = _key_params(tv)
    key = derive_traffic_key(tv["kdf_alg"], mk, src, dst, sp, dp, si, di)

    exp_key = bytes.fromhex(tv["expected_traffic_key"])
    key_ok = key == exp_key

    pkt = bytes.fromhex(tv["packet_hex"])
    mi = build_mac_input(tv["sne"], pkt, tv["covers_options"])
    mac = compute_mac(tv["mac_alg"], key, mi)

    exp_mac = bytes.fromhex(tv["expected_mac"])
    mac_ok = mac == exp_mac

    return key_ok, mac_ok, key.hex(), mac.hex()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    with open("/app/test_vectors.json") as f:
        vectors = json.load(f)

    total = len(vectors)
    kp = mp = 0
    for tv in vectors:
        ko, mo, ck, cm = verify(tv)
        kp += int(ko)
        mp += int(mo)
        print(f"[{tv['id']}] Key:{'OK' if ko else 'FAIL'}  "
              f"MAC:{'OK' if mo else 'FAIL'}  {tv['description']}")
        if not ko:
            print(f"       key exp={tv['expected_traffic_key']}")
            print(f"       key got={ck}")
        if not mo:
            print(f"       mac exp={tv['expected_mac']}")
            print(f"       mac got={cm}")

    print(f"\nTraffic keys: {kp}/{total}   MACs: {mp}/{total}")
    return kp == total and mp == total


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
