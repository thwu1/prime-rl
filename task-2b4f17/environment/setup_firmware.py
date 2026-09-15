#!/usr/bin/env python3
"""
Generate the FWPK firmware image for this task.
Runs during Docker build (builder stage) and is never present in the final image.
"""

import struct
import hashlib
import binascii
import gzip
import json
import os
import hmac as hmac_mod

from cryptography.hazmat.primitives.asymmetric import rsa, padding as asym_padding
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend


# ===================== Primality Utilities =====================

SMALL_PRIMES = [
    2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37,
    41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97,
]


def is_probable_prime(n):
    """Deterministic Miller-Rabin with 25 small-prime witnesses."""
    if n < 2:
        return False
    for sp in SMALL_PRIMES:
        if n == sp:
            return True
        if n % sp == 0:
            return False
    r, d = 0, n - 1
    while d % 2 == 0:
        r += 1
        d //= 2
    for a in SMALL_PRIMES:
        if a >= n:
            continue
        x = pow(a, d, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def next_prime_after(n):
    """Return the smallest prime strictly greater than n."""
    c = n + 1
    if c % 2 == 0:
        c += 1
    while not is_probable_prime(c):
        c += 2
    return c


# ===================== FWPK Binary Format =====================

FWPK_MAGIC = b"FWPK"
FWPK_VERSION = 0x0102
SEC_ENTRY_SZ = 32


def mk_section_entry(name, offset, size, flags):
    name_b = name.encode("ascii")[:16].ljust(16, b"\x00")
    return struct.pack("<16sIIII", name_b, offset, size, flags, 0)


def build_fwpk(sections):
    """
    Build FWPK container from [(name, data, flags), ...].

    Header (12 bytes):
      [0:4]   Magic "FWPK"
      [4:6]   Version (uint16 LE)
      [6:8]   Section count (uint16 LE)
      [8:12]  CRC32 over magic+version+count+table (uint32 LE)

    Section table (32 bytes each):
      [0:16]  Name (ASCII, null-padded)
      [16:20] Offset from file start (uint32 LE)
      [20:24] Size (uint32 LE)
      [24:28] Flags (uint32 LE) -- 0x01=gzip, 0x02=encrypted
      [28:32] Reserved
    """
    num = len(sections)
    hdr_sz = 12 + num * SEC_ENTRY_SZ

    entries = []
    cur = hdr_sz
    for name, data, flags in sections:
        entries.append((name, cur, len(data), flags))
        cur += len(data)

    table = b""
    for name, off, sz, fl in entries:
        table += mk_section_entry(name, off, sz, fl)

    pre = struct.pack("<4sHH", FWPK_MAGIC, FWPK_VERSION, num)
    crc = binascii.crc32(pre + table) & 0xFFFFFFFF
    hdr = pre + struct.pack("<I", crc)

    blob = hdr + table
    for _, data, _ in sections:
        blob += data
    return blob


# ===================== Diagnostic Log =====================

DIAGNOSTIC_LOG = """\
=== VEHICLE DIAGNOSTIC DATABASE v3.2.1 ===
System: IVI-ECU Module R7 (Infotainment Controller Unit)
VIN: 5YJ3E1EAXNF384721
Capture Date: 2024-11-22T08:15:33Z
Firmware Version: v4.8.2-release-20241101
Hardware Revision: C3-PROD
Serial Number: IVI-2024-038847-R7C3
===========================================

--- DIAGNOSTIC RECORD 001 ---
Timestamp: 2024-11-22T07:03:11Z
Module: ADAS_FRONT_CAMERA
Status: DEGRADED
Error Code: E-4401
Description: Calibration drift detected in forward-facing camera module.
  Yaw offset: +0.032 rad
  Pitch offset: -0.018 rad
  Last calibration: 2024-09-15T10:00:00Z
Recommended Action: Schedule recalibration at authorized service center.
Priority: HIGH

--- DIAGNOSTIC RECORD 002 ---
Timestamp: 2024-11-22T07:03:12Z
Module: TPMS_CONTROLLER
Status: WARNING
Error Code: W-2207
Description: Tire pressure sensor FL intermittent signal loss.
  Signal strength: -82 dBm (threshold: -75 dBm)
  Battery voltage: 2.1V (nominal: 3.0V)
  Sensor ID: TPMS-FL-A7E2
Recommended Action: Replace FL tire pressure sensor at next service.
Priority: MEDIUM

--- DIAGNOSTIC RECORD 003 ---
Timestamp: 2024-11-22T07:03:13Z
Module: BATTERY_MANAGEMENT_SYSTEM
Status: NOMINAL
  Pack Voltage: 398.4V
  State of Charge: 78.2%
  Pack Temperature: 28.3C
  Cell Balance Delta: 0.012V
  Charge Cycles: 847
  State of Health: 94.1%
  Max Cell Voltage: 4.18V (Cell #47)
  Min Cell Voltage: 4.17V (Cell #12)

--- DIAGNOSTIC RECORD 004 ---
Timestamp: 2024-11-22T07:03:14Z
Module: TELEMATICS_UNIT
Status: FAULT
Error Code: E-6619
Description: Cellular modem failed to register on network.
  Last successful connection: 2024-11-21T23:45:00Z
  IMEI: 356938035643809
  ICCID: 8901260852345678901
  APN: iot.vehicle.net
  Signal: NO_SIGNAL
Recommended Action: Check SIM provisioning and antenna connection.
Priority: HIGH

--- DIAGNOSTIC RECORD 005 ---
Timestamp: 2024-11-22T07:03:15Z
Module: HVAC_CONTROLLER
Status: NOMINAL
  Cabin Temperature: 22.1C
  Set Temperature: 22.0C
  Compressor Duty Cycle: 34%
  Blower Speed: Level 3
  Refrigerant Pressure: 2.14 MPa
  Air Quality Index: 42 (Good)
  Recirculation: AUTO

--- DIAGNOSTIC RECORD 006 ---
Timestamp: 2024-11-22T07:03:16Z
Module: INSTRUMENT_CLUSTER
Status: NOMINAL
  Odometer: 45287.3 km
  Trip A: 234.1 km
  Trip B: 1023.8 km
  Display Brightness: AUTO (ambient: 4200 lux)
  Active Warning Lights: TPMS_ACTIVE
  Fuel Economy (avg): 15.2 kWh/100km

--- DIAGNOSTIC RECORD 007 ---
Timestamp: 2024-11-22T07:03:17Z
Module: OBD_GATEWAY
  DTC Active: P0456 (EVAP System Small Leak), U0155 (IPC Lost Comms)
  DTC Pending: None
  DTC History: C1234, P0301, U0100
  Freeze Frame: Yes (P0456 at odometer 44982.1 km)
  MIL Status: ON
  Readiness: EVAP_NOT_READY, O2S_READY, CAT_READY

--- SECURITY AUDIT SECTION ---
Generated: 2024-11-22T08:15:33Z
Audit ID: AUD-20241122-081533-R7C3
Auth Token: DIAG-7f3a9b2c-e841-4d05-b6f3-8a9c2d1e4f07
Access Level: TIER_3_ENGINEERING
Session Nonce: 0x4a7f2e91b3d508c6
Certificate CN: DiagTool-v4.2
Organization: VehicleCorp Automotive
Clearance: FULL_DIAGNOSTICS_RW
Key Fingerprint: SHA256:e4b7a2f9c1d638509a721be445cd9073
Signature: HMAC-SHA256:9f8e7d6c5b4a39281706f5e4d3c2b1a0
Audit Trail Hash: SHA384:2c7f8a9b0e1d4f3a6b5c8d7e

--- END OF DIAGNOSTIC DATABASE ---
Record Count: 7
Fault Count: 2
Warning Count: 1
Database CRC32: 0xA4E8F21B
Export Timestamp: 2024-11-22T08:15:34Z
"""


def main():
    os.makedirs("/app", exist_ok=True)

    # ---- 1. Generate weak RSA-1024 (close primes -> Fermat-factorable) ----
    h1 = hashlib.sha512(b"fwpk-rsa-prime-base-v3").digest()
    base_p = int.from_bytes(h1, "big")
    base_p |= (1 << 511)
    base_p |= 1

    p = next_prime_after(base_p)

    delta_raw = hashlib.sha256(b"fwpk-prime-delta-v3").digest()
    delta = int.from_bytes(delta_raw[:2], "big")
    delta = max(delta, 500)

    q = next_prime_after(p + delta)

    # RSA CRT convention: p > q
    if p < q:
        p, q = q, p

    n = p * q
    e = 65537
    phi = (p - 1) * (q - 1)
    d = pow(e, -1, phi)
    dp = d % (p - 1)
    dq = d % (q - 1)
    qi = pow(q, -1, p)

    pub_nums = rsa.RSAPublicNumbers(e, n)
    priv_nums = rsa.RSAPrivateNumbers(p, q, d, dp, dq, qi, pub_nums)
    enc_priv = priv_nums.private_key(default_backend())
    enc_pub = enc_priv.public_key()

    pubkey_der = enc_pub.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    print(f"RSA-{n.bit_length()} key, |p-q| = {abs(p - q)}")

    # ---- 2. AES-256 session key (deterministic) ----
    aes_key = hashlib.sha256(b"fwpk-aes-session-key-v3").digest()

    # ---- 3. Mask and wrap AES key ----
    # Key masking: XOR session key with SHA-256(pubkey_der) before RSA wrapping.
    # This binds the wrapped key to its intended RSA recipient, preventing
    # naive key extraction even if PKCS#1v1.5 is broken.
    key_mask = hashlib.sha256(pubkey_der).digest()
    masked_key = bytes(a ^ b for a, b in zip(aes_key, key_mask))
    wrapped_key = enc_pub.encrypt(masked_key, asym_padding.PKCS1v15())

    # ---- 4. Read & compress key-management module ----
    with open("/tmp/key_mgmt.py", "r") as f:
        keymgmt_src = f.read()
    keymgmt_gz = gzip.compress(keymgmt_src.encode("utf-8"))

    # ---- 5. Encrypt diagnostic data across 3 partitions ----
    plaintext = DIAGNOSTIC_LOG.encode("utf-8")
    part_sz = len(plaintext) // 3
    parts = [
        plaintext[:part_sz],
        plaintext[part_sz:2 * part_sz],
        plaintext[2 * part_sz:],
    ]

    enc_parts = []
    for i, raw in enumerate(parts):
        iv = hmac_mod.new(
            aes_key, struct.pack(">I", i), hashlib.sha256
        ).digest()[:16]
        pad_len = 16 - (len(raw) % 16)
        padded = raw + bytes([pad_len]) * pad_len
        cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv))
        encryptor = cipher.encryptor()
        enc_parts.append(encryptor.update(padded) + encryptor.finalize())

    # ---- 6. Manifest (plaintext JSON) ----
    manifest = json.dumps({
        "firmware_id": "IVI-ECU-R7-4.8.2",
        "build_date": "2024-11-01T00:00:00Z",
        "target": "IVI-ECU-R7-C3",
        "crypto": {
            "key_wrap": "RSA-PKCS1v15",
            "key_mask": "SHA256-pubkey-XOR",
            "data_cipher": "AES-256-CBC",
            "iv_method": "HMAC-SHA256-derived",
            "key_mgmt_module": "key_mgmt (gzip-compressed)",
        },
        "partitions": ["partition_0", "partition_1", "partition_2"],
    }, indent=2).encode("utf-8")

    # ---- 7. Build FWPK container ----
    sections = [
        ("manifest",       manifest,       0x00),
        ("rsa_pubkey",     pubkey_der,     0x00),
        ("wrapped_aeskey", wrapped_key,    0x02),
        ("key_mgmt",       keymgmt_gz,    0x01),
        ("partition_0",    enc_parts[0],   0x02),
        ("partition_1",    enc_parts[1],   0x02),
        ("partition_2",    enc_parts[2],   0x02),
    ]

    firmware = build_fwpk(sections)

    with open("/app/firmware.bin", "wb") as f:
        f.write(firmware)

    # ---- 8. Verification artifacts (hidden dot-files) ----
    with open("/app/.diag_verify", "w") as f:
        f.write(hashlib.sha256(plaintext).hexdigest())

    token = "DIAG-7f3a9b2c-e841-4d05-b6f3-8a9c2d1e4f07"
    with open("/app/.token_verify", "w") as f:
        f.write(hashlib.sha256(token.encode()).hexdigest())

    # Store RSA public key DER for test verification
    with open("/app/.pubkey_der", "wb") as f:
        f.write(pubkey_der)

    # Store a deterministic RSA signature for key verification
    # (PKCS1v15 + SHA256 is deterministic, independent of CRT ordering)
    test_msg = b"fwpk-key-verification-challenge-v3"
    sig = enc_priv.sign(test_msg, asym_padding.PKCS1v15(), hashes.SHA256())
    with open("/app/.sig_verify", "wb") as f:
        f.write(sig)

    # NOTE: RSA-2048 key pair for hardened firmware is generated separately
    # via openssl in the final Dockerfile stage (not here) for build reliability.

    print(f"Firmware: {len(firmware)} bytes, {len(sections)} sections")
    print(f"Plaintext: {len(plaintext)} bytes across {len(parts)} partitions")
    print(f"SHA256: {hashlib.sha256(plaintext).hexdigest()}")


if __name__ == "__main__":
    main()
