#!/usr/bin/env python3
"""Diagnostic: run known test vectors against the ACVP module."""
import subprocess
import struct
import hashlib
import hmac as hmac_mod
import sys


def write_request(proc, *args):
    n = len(args)
    buf = struct.pack('<I', n)
    for a in args:
        buf += struct.pack('<I', len(a))
    for a in args:
        buf += a
    proc.stdin.write(buf)
    proc.stdin.flush()


def read_response(proc):
    raw = proc.stdout.read(4)
    if not raw or len(raw) < 4:
        print("ERROR: no response from module", file=sys.stderr)
        sys.exit(1)
    n = struct.unpack('<I', raw)[0]
    lengths = []
    for _ in range(n):
        raw = proc.stdout.read(4)
        lengths.append(struct.unpack('<I', raw)[0])
    result = []
    for l in lengths:
        data = proc.stdout.read(l) if l > 0 else b''
        result.append(data)
    return result


def check(label, got, expected):
    if got == expected:
        print(f"  PASS  {label}")
        return True
    else:
        print(f"  FAIL  {label}")
        print(f"        expected: {expected.hex()}")
        print(f"        got:      {got.hex()}")
        return False


def main():
    proc = subprocess.Popen(
        ['/app/acvp_module'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    passed = 0
    total = 0

    # --- SHA2-256 ---
    total += 1
    msg = b'abc'
    write_request(proc, b'SHA2-256', msg)
    r = read_response(proc)
    if check("SHA2-256('abc')", r[0], hashlib.sha256(msg).digest()):
        passed += 1

    # --- HMAC-SHA2-256 (RFC 4231 Test Case 2) ---
    total += 1
    hmac_key = b'Jefe'
    hmac_msg = b'what do ya want for nothing?'
    # ACVP argument order: message first, then key
    write_request(proc, b'HMAC-SHA2-256', hmac_msg, hmac_key)
    r = read_response(proc)
    expected_hmac = hmac_mod.new(hmac_key, hmac_msg, hashlib.sha256).digest()
    if check("HMAC-SHA2-256 RFC4231#2", r[0], expected_hmac):
        passed += 1

    # --- AES-256-GCM/seal (NIST SP 800-38D Test Case 14, non-empty PT) ---
    total += 1
    tag_len_bytes = struct.pack('<I', 16)
    key_gcm = b'\x00' * 32
    nonce = b'\x00' * 12
    pt = b'\x00' * 16
    write_request(proc, b'AES-256-GCM/seal', tag_len_bytes, key_gcm, pt, nonce, b'')
    r = read_response(proc)
    expected_ct = bytes.fromhex('cea7403d4d606b6e074ec5d3baf39d18')
    expected_tag = bytes.fromhex('d0d1c8a799996bf0265b98b5d48ab919')
    expected_seal = expected_ct + expected_tag  # ct || tag per ACVP spec
    if check("AES-256-GCM/seal NIST#14", r[0], expected_seal):
        passed += 1

    # --- AES-256-GCM round-trip (seal then open) ---
    total += 1
    key_rt = bytes(range(32))
    nonce_rt = bytes(range(12))
    pt_rt = b'round-trip test data'
    write_request(proc, b'AES-256-GCM/seal', tag_len_bytes, key_rt, pt_rt, nonce_rt, b'aad')
    r_seal = read_response(proc)
    write_request(proc, b'AES-256-GCM/open', tag_len_bytes, key_rt, r_seal[0], nonce_rt, b'aad')
    r_open = read_response(proc)
    if r_open[0] == b'\x01' and r_open[1] == pt_rt:
        print(f"  PASS  AES-256-GCM round-trip")
        passed += 1
    else:
        print(f"  FAIL  AES-256-GCM round-trip")

    # --- HKDF/SHA2-256 (RFC 5869 Test Case 1) ---
    total += 1
    ikm = bytes.fromhex('0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b')
    salt = bytes.fromhex('000102030405060708090a0b0c')
    info = bytes.fromhex('f0f1f2f3f4f5f6f7f8f9')
    out_len = struct.pack('<I', 42)
    write_request(proc, b'HKDF/SHA2-256', ikm, salt, info, out_len)
    r = read_response(proc)
    expected_okm = bytes.fromhex(
        '3cb25f25faacd57a90434f64d0362f2a'
        '2d2d0a90cf1a5a4c5db02d56ecc4c5bf'
        '34007208d5b887185865')
    if check("HKDF/SHA2-256 RFC5869#1", r[0], expected_okm):
        passed += 1

    # --- CMAC-AES-256 (NIST SP 800-38B D.2 Example 3, 40-byte message) ---
    total += 1
    cmac_key = bytes.fromhex(
        '603deb1015ca71be2b73aef0857d7781'
        '1f352c073b6108d72d9810a30914dff4')
    cmac_msg = bytes.fromhex(
        '6bc1bee22e409f96e93d7e117393172a'
        'ae2d8a571e03ac9c9eb76fac45af8e51'
        '30c81c46a35ce411')
    cmac_out_len = struct.pack('<I', 16)
    write_request(proc, b'CMAC-AES-256', cmac_out_len, cmac_key, cmac_msg)
    r = read_response(proc)
    expected_cmac = bytes.fromhex('aaf3d8f1de5640c232f5b169b9c911e6')
    if check("CMAC-AES-256 NIST-D2#3", r[0], expected_cmac):
        passed += 1

    # --- PBKDF2-HMAC-SHA256 (P="password", S="salt", c=4096, dkLen=32) ---
    total += 1
    password = b'password'
    pbkdf2_salt = b'salt'
    iterations = struct.pack('<I', 4096)
    dk_len = struct.pack('<I', 32)
    write_request(proc, b'PBKDF2-HMAC-SHA256', password, pbkdf2_salt, iterations, dk_len)
    r = read_response(proc)
    expected_dk = hashlib.pbkdf2_hmac('sha256', password, pbkdf2_salt, 4096, dklen=32)
    if check("PBKDF2-HMAC-SHA256 c=4096", r[0], expected_dk):
        passed += 1

    proc.stdin.close()
    proc.wait(timeout=5)

    print(f"\n{passed}/{total} tests passed")
    sys.exit(0 if passed == total else 1)


if __name__ == '__main__':
    main()
