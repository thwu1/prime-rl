#!/usr/bin/env python3
"""
TCP-AO Forensic Packet Authentication Analyzer.

Implements full TCP-AO traffic key derivation (KDF) and MAC computation
per RFC 5925/5926, then classifies packets as authentic or forged.

"""

import json
import hmac
import hashlib
import struct
import ipaddress


# ---------------------------------------------------------------------------
# AES-CMAC (RFC 4493)
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
    assert len(key) == 16
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
# KDF (RFC 5926 Section 3.1.1)
# ---------------------------------------------------------------------------

def kdf_hmac_sha1(master_key, context, output_length_bits):
    label = b"TCP-AO"
    out_len = struct.pack("!H", output_length_bits)
    result = b""
    blocks = (output_length_bits + 159) // 160
    for i in range(1, blocks + 1):
        data = struct.pack("B", i) + label + context + out_len
        result += hmac.new(master_key, data, hashlib.sha1).digest()
    return result[:output_length_bits // 8]


def kdf_aes_128_cmac(master_key, context, output_length_bits):
    label = b"TCP-AO"
    out_len = struct.pack("!H", output_length_bits)
    if len(master_key) == 16:
        k = master_key
    else:
        k = aes_cmac(b'\x00' * 16, master_key)
    result = b""
    blocks = (output_length_bits + 127) // 128
    for i in range(1, blocks + 1):
        data = struct.pack("B", i) + label + context + out_len
        result += aes_cmac(k, data)
    return result[:output_length_bits // 8]


# ---------------------------------------------------------------------------
# KDF Context (RFC 5925 Section 5.2)
# ---------------------------------------------------------------------------

def build_context(src_addr, dst_addr, src_port, dst_port, src_isn, dst_isn):
    return (src_addr + dst_addr
            + struct.pack("!H", src_port) + struct.pack("!H", dst_port)
            + struct.pack("!I", src_isn) + struct.pack("!I", dst_isn))


def derive_traffic_key(pkt_info, master_key):
    kdf_alg = pkt_info["kdf_alg"]
    direction = pkt_info["direction"]
    seg_type = pkt_info["segment_type"]

    client_ip = ipaddress.ip_address(pkt_info["client_ip"]).packed
    server_ip = ipaddress.ip_address(pkt_info["server_ip"]).packed
    client_port = pkt_info["client_port"]
    server_port = pkt_info["server_port"]
    client_isn = int(pkt_info["client_isn"], 16)
    server_isn = int(pkt_info["server_isn"], 16)

    if seg_type == "SYN":
        # Client sends SYN; remote ISN not yet known => 0
        src_addr, dst_addr = client_ip, server_ip
        sp, dp = client_port, server_port
        si, di = client_isn, 0
    elif seg_type == "SYN-ACK":
        # Server sends SYN-ACK; both ISNs known
        src_addr, dst_addr = server_ip, client_ip
        sp, dp = server_port, client_port
        si, di = server_isn, client_isn
    else:  # DATA
        if direction == "client_to_server":
            src_addr, dst_addr = client_ip, server_ip
            sp, dp = client_port, server_port
            si, di = client_isn, server_isn
        else:
            src_addr, dst_addr = server_ip, client_ip
            sp, dp = server_port, client_port
            si, di = server_isn, client_isn

    ctx = build_context(src_addr, dst_addr, sp, dp, si, di)

    if kdf_alg == "HMAC-SHA1":
        return kdf_hmac_sha1(master_key, ctx, 160)
    else:
        return kdf_aes_128_cmac(master_key, ctx, 128)


# ---------------------------------------------------------------------------
# Packet parsing and MAC input construction (RFC 5925 Section 5.1)
# ---------------------------------------------------------------------------

def find_ao_option(tcp, hdr_len):
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


def extract_packet_mac(pkt_bytes):
    ver = (pkt_bytes[0] >> 4) & 0xf
    if ver == 4:
        tcp_off = (pkt_bytes[0] & 0xf) * 4
    else:
        tcp_off = 40

    tcp = pkt_bytes[tcp_off:]
    tcp_hdr_len = ((tcp[12] >> 4) & 0xf) * 4
    ao_off, ao_len = find_ao_option(tcp, tcp_hdr_len)
    if ao_off is None:
        return None
    mac_start = ao_off + 4
    mac_sz = ao_len - 4
    return bytes(tcp[mac_start:mac_start + mac_sz])


def build_mac_input(sne, packet, covers_options):
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
    else:
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

    # Zero the TCP checksum (RFC 5925)
    tcp[16:18] = b'\x00\x00'

    # Zero the MAC field inside TCP-AO option
    ao_off, ao_len = find_ao_option(tcp, tcp_hdr_len)
    if ao_off is not None:
        mac_start = ao_off + 4
        mac_sz = ao_len - 4
        tcp[mac_start:mac_start + mac_sz] = b'\x00' * mac_sz

    sne_bytes = struct.pack("!I", sne)

    if covers_options:
        hdr = bytes(tcp[:tcp_hdr_len])
    else:
        hdr = bytes(tcp[:20])
        if ao_off is not None:
            hdr += bytes(tcp[ao_off:ao_off + ao_len])

    payload = bytes(tcp[tcp_hdr_len:])
    return sne_bytes + pseudo + hdr + payload


def compute_mac(mac_alg, traffic_key, mac_input):
    if mac_alg == "HMAC-SHA-1-96":
        return hmac.new(traffic_key, mac_input, hashlib.sha1).digest()[:12]
    else:  # AES-128-CMAC-96
        return aes_cmac(traffic_key, mac_input)[:12]


# ---------------------------------------------------------------------------
# Forensic analysis
# ---------------------------------------------------------------------------

def analyze_packet(pkt_info, master_key):
    pkt_bytes = bytes.fromhex(pkt_info["hex"])
    packet_mac = extract_packet_mac(pkt_bytes)
    traffic_key = derive_traffic_key(pkt_info, master_key)

    # Compute MAC with stated parameters
    mac_input = build_mac_input(pkt_info["sne"], pkt_bytes, pkt_info["covers_options"])
    computed_mac = compute_mac(pkt_info["mac_alg"], traffic_key, mac_input)

    if computed_mac == packet_mac:
        return {
            "verdict": "authentic",
            "computed_mac": computed_mac.hex(),
            "packet_mac": packet_mac.hex(),
            "attack_class": None,
        }

    # Hypothesis 1: wrong TCP options coverage mode
    alt_covers = not pkt_info["covers_options"]
    alt_input = build_mac_input(pkt_info["sne"], pkt_bytes, alt_covers)
    alt_mac = compute_mac(pkt_info["mac_alg"], traffic_key, alt_input)

    if alt_mac == packet_mac:
        return {
            "verdict": "forged",
            "computed_mac": computed_mac.hex(),
            "packet_mac": packet_mac.hex(),
            "attack_class": "wrong_coverage",
        }

    # Hypothesis 2: MAC field directly corrupted (few bytes differ)
    diff_count = sum(1 for a, b in zip(computed_mac, packet_mac) if a != b)

    if diff_count <= 3:
        return {
            "verdict": "forged",
            "computed_mac": computed_mac.hex(),
            "packet_mac": packet_mac.hex(),
            "attack_class": "corrupted_mac",
        }

    # Hypothesis 3: payload was modified after MAC computation
    return {
        "verdict": "forged",
        "computed_mac": computed_mac.hex(),
        "packet_mac": packet_mac.hex(),
        "attack_class": "modified_payload",
    }


def main():
    with open("/app/scenario.json") as f:
        scenario = json.load(f)

    master_key = scenario["master_key"].encode("ascii")
    report = {}

    for pkt in scenario["packets"]:
        result = analyze_packet(pkt, master_key)
        report[pkt["id"]] = result

    with open("/app/audit_report.json", "w") as f:
        json.dump(report, f, indent=2)

    authentic = sum(1 for r in report.values() if r["verdict"] == "authentic")
    forged = sum(1 for r in report.values() if r["verdict"] == "forged")
    print(f"Analysis complete: {authentic} authentic, {forged} forged out of {len(report)} packets")
    for pid, r in sorted(report.items()):
        line = f"  {pid}: {r['verdict']}"
        if r["attack_class"]:
            line += f" ({r['attack_class']})"
        print(line)


if __name__ == "__main__":
    main()
