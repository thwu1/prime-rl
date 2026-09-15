
"""
AES-CBC Monte Carlo Test solver.
Implements the NIST AESAVS MCT algorithm for encrypt and decrypt directions,
supporting 128/192/256-bit key sizes.
"""

import json
import re
import os
from Crypto.Cipher import AES


def xor_bytes(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def mct_cbc_encrypt_inner(key: bytes, iv: bytes, pt: bytes):
    """Run 1000 inner-loop iterations for AES-CBC MCT encrypt.

    The MCT inner loop for CBC encrypt:
      j=0: CT[0] = E_K(PT XOR IV)
      j=1: CT[1] = E_K(IV XOR CT[0])     (PT[1] = IV)
      j>=2: CT[j] = E_K(CT[j-2] XOR CT[j-1])

    Returns (ct_998, ct_999).
    """
    cipher = AES.new(key, AES.MODE_ECB)

    # j=0
    ct_0 = cipher.encrypt(xor_bytes(pt, iv))
    # j=1: PT[1] = IV
    ct_1 = cipher.encrypt(xor_bytes(iv, ct_0))

    # j=2..999: CT[j] = E_K(CT[j-2] XOR CT[j-1])
    prev_prev = ct_0
    prev = ct_1
    for _ in range(2, 1000):
        curr = cipher.encrypt(xor_bytes(prev_prev, prev))
        prev_prev = prev
        prev = curr

    return prev_prev, prev  # ct_998, ct_999


def mct_cbc_decrypt_inner(key: bytes, iv: bytes, ct: bytes):
    """Run 1000 inner-loop iterations for AES-CBC MCT decrypt.

    The MCT inner loop for CBC decrypt:
      j=0: PT[0] = D_K(CT) XOR IV
      j=1: PT[1] = D_K(IV) XOR PT[0]     (CT[1] = IV)
      j>=2: PT[j] = D_K(PT[j-2]) XOR PT[j-1]

    Returns (pt_998, pt_999).
    """
    cipher = AES.new(key, AES.MODE_ECB)

    # j=0
    pt_0 = xor_bytes(cipher.decrypt(ct), iv)
    # j=1: CT[1] = IV
    pt_1 = xor_bytes(cipher.decrypt(iv), pt_0)

    # j=2..999
    prev_prev = pt_0
    prev = pt_1
    for _ in range(2, 1000):
        curr = xor_bytes(cipher.decrypt(prev_prev), prev)
        prev_prev = prev
        prev = curr

    return prev_prev, prev  # pt_998, pt_999


def derive_key(key: bytes, block_998: bytes, block_999: bytes, key_bits: int) -> bytes:
    """Derive the next outer-iteration key by XORing with recent output blocks.

    128-bit: key XOR block_999
    192-bit: key XOR (last 8 bytes of block_998 || block_999)
    256-bit: key XOR (block_998 || block_999)
    """
    if key_bits == 128:
        return xor_bytes(key, block_999)
    elif key_bits == 192:
        return xor_bytes(key, block_998[-8:] + block_999)
    elif key_bits == 256:
        return xor_bytes(key, block_998 + block_999)
    else:
        raise ValueError(f"Unsupported key size: {key_bits}")


def run_mct_encrypt(key_hex, iv_hex, pt_hex, key_bits, required_counts):
    key = bytes.fromhex(key_hex)
    iv = bytes.fromhex(iv_hex)
    pt = bytes.fromhex(pt_hex)
    results = {}

    for i in range(100):
        ct_998, ct_999 = mct_cbc_encrypt_inner(key, iv, pt)
        if i in required_counts:
            results[str(i)] = {
                "KEY": key.hex(),
                "IV": iv.hex(),
                "PLAINTEXT": pt.hex(),
                "CIPHERTEXT": ct_999.hex(),
            }
        key = derive_key(key, ct_998, ct_999, key_bits)
        iv = ct_999
        pt = ct_998

    return results


def run_mct_decrypt(key_hex, iv_hex, ct_hex, key_bits, required_counts):
    key = bytes.fromhex(key_hex)
    iv = bytes.fromhex(iv_hex)
    ct = bytes.fromhex(ct_hex)
    results = {}

    for i in range(100):
        pt_998, pt_999 = mct_cbc_decrypt_inner(key, iv, ct)
        if i in required_counts:
            results[str(i)] = {
                "KEY": key.hex(),
                "IV": iv.hex(),
                "CIPHERTEXT": ct.hex(),
                "PLAINTEXT": pt_999.hex(),
            }
        key = derive_key(key, pt_998, pt_999, key_bits)
        iv = pt_999
        ct = pt_998

    return results


def parse_rsp(path):
    entries = []
    current = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("#") or line.startswith("[") or not line:
                if current:
                    entries.append(current)
                    current = {}
                continue
            m = re.match(r"(\w+)\s*=\s*(.+)", line)
            if m:
                current[m.group(1)] = m.group(2).strip()
    if current:
        entries.append(current)
    return entries


def audit_rsp(path, key_bits=128):
    entries = parse_rsp(path)
    corruptions = []
    for entry in entries:
        count = int(entry["COUNT"])
        key = bytes.fromhex(entry["KEY"])
        iv = bytes.fromhex(entry["IV"])
        pt = bytes.fromhex(entry["PLAINTEXT"])
        file_ct = entry["CIPHERTEXT"].lower()
        _, ct_999 = mct_cbc_encrypt_inner(key, iv, pt)
        expected_ct = ct_999.hex()
        if file_ct != expected_ct:
            corruptions.append({
                "count": count,
                "found": file_ct,
                "expected": expected_ct,
            })
    return corruptions


def main():
    with open("/app/challenge.json") as f:
        challenge = json.load(f)

    output = {"compute": {}, "audit": {}}

    # Process compute tasks
    for task in challenge["compute"]:
        tid = task["id"]
        direction = task["direction"]
        key_bits = task["key_bits"]
        rc = task["required_counts"]

        if direction == "encrypt":
            output["compute"][tid] = run_mct_encrypt(
                task["key"], task["iv"], task["plaintext"], key_bits, rc,
            )
        elif direction == "decrypt":
            output["compute"][tid] = run_mct_decrypt(
                task["key"], task["iv"], task["ciphertext"], key_bits, rc,
            )

    # Process audit tasks
    for task in challenge["audit"]:
        tid = task["id"]
        path = task["file"]
        key_bits = task["key_bits"]
        output["audit"][tid] = audit_rsp(path, key_bits)

    with open("/app/results.json", "w") as f:
        json.dump(output, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
