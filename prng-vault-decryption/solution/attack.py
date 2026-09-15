#!/usr/bin/env python3
"""
Attack script for the Secure Vault challenge.

Part 1: Recovers the flag by exploiting the MT19937 PRNG state leaked
through the obfuscated calibration diagnostic log.

Steps:
  1. Parse and de-obfuscate the 624 calibration outputs from debug_log.txt
  2. Untemper each output to recover the MT19937 internal state
  3. Clone a Python random.Random with the recovered state
  4. Replay the PRNG to regenerate RSA primes, AES key, and nonce
  5. Derive the RSA private key and decrypt the AES session key
  6. Decrypt the flag with AES-CTR

Part 2: Evaluates proposed security patches for effectiveness.
"""

import random
import json
import sys
import os

sys.path.insert(0, "/app/vault")
from crypto_utils import is_probable_prime, generate_prime

from Crypto.Cipher import AES


def deobfuscate_calibration(obfuscated, index):
    """Reverse the obfuscation applied to calibration outputs."""
    mask = (0x6c078965 * (index + 1)) & 0xffffffff
    xored = obfuscated ^ mask
    shift = index % 32
    if shift == 0:
        return xored
    return ((xored >> shift) | (xored << (32 - shift))) & 0xffffffff


def untemper(y):
    """
    Reverse the MT19937 tempering transform to recover
    the internal state word from an observed output.
    """
    # Invert y ^= (y >> 18)
    y ^= (y >> 18)

    # Invert y ^= (y << 15) & 0xefc60000
    y ^= (y << 15) & 0xefc60000

    # Invert y ^= (y << 7) & 0x9d2c5680
    tmp = y
    for _ in range(4):
        tmp = y ^ ((tmp << 7) & 0x9d2c5680)
    y = tmp

    # Invert y ^= (y >> 11)
    tmp = y
    for _ in range(3):
        tmp = y ^ (tmp >> 11)
    y = tmp

    return y & 0xffffffff


def recover_flag():
    """Exploit the PRNG leak to recover the encrypted flag."""
    data_dir = "/app/vault/data"

    # Step 1: Parse the debug log
    print("[*] Parsing calibration diagnostic log...")
    calibration = []
    with open(os.path.join(data_dir, "debug_log.txt")) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            idx_str, val_str = line.split(": ")
            calibration.append(int(val_str, 16))
    assert len(calibration) == 624, f"Expected 624 entries, got {len(calibration)}"

    # Step 2: De-obfuscate to recover raw MT outputs
    print("[*] De-obfuscating calibration outputs...")
    raw_outputs = [deobfuscate_calibration(calibration[i], i) for i in range(624)]

    # Step 3: Untemper to recover MT internal state
    print("[*] Recovering MT19937 internal state...")
    state = [untemper(x) for x in raw_outputs]

    # Step 4: Clone the PRNG
    print("[*] Cloning PRNG...")
    cloned_rng = random.Random()
    cloned_rng.setstate((3, tuple(state + [624]), None))

    # Step 5: Replay the PRNG sequence
    print("[*] Regenerating RSA primes...")
    p = generate_prime(cloned_rng, 512)
    q = generate_prime(cloned_rng, 512)

    print(f"[+] p = {hex(p)[:20]}...")
    print(f"[+] q = {hex(q)[:20]}...")

    aes_key = cloned_rng.getrandbits(128).to_bytes(16, "big")
    nonce = cloned_rng.getrandbits(64).to_bytes(8, "big")

    # Verify nonce matches stored value
    with open(os.path.join(data_dir, "aes_nonce.hex")) as f:
        stored_nonce = bytes.fromhex(f.read().strip())
    assert nonce == stored_nonce, "Nonce mismatch - PRNG state recovery failed"
    print("[+] Nonce verification: PASS")

    # Step 6: Derive RSA private key
    print("[*] Computing RSA private key...")
    n = p * q
    e = 65537
    phi_n = (p - 1) * (q - 1)
    d = pow(e, -1, phi_n)

    # Verify against stored public key
    with open(os.path.join(data_dir, "pubkey.json")) as f:
        pubkey = json.load(f)
    stored_n = int(pubkey["n"], 16)
    assert n == stored_n, "RSA modulus mismatch"
    print("[+] RSA modulus verification: PASS")

    # Step 7: Decrypt AES key
    print("[*] Decrypting AES session key...")
    with open(os.path.join(data_dir, "encrypted_aes_key.hex")) as f:
        encrypted_aes_key = int(f.read().strip(), 16)
    decrypted_key_int = pow(encrypted_aes_key, d, n)
    decrypted_key = decrypted_key_int.to_bytes(16, "big")

    assert decrypted_key == aes_key, "AES key decryption mismatch"
    print("[+] AES key decryption: PASS")

    # Step 8: Decrypt the flag
    print("[*] Decrypting vault contents...")
    with open(os.path.join(data_dir, "encrypted_flag.hex")) as f:
        encrypted_flag = bytes.fromhex(f.read().strip())
    cipher = AES.new(decrypted_key, AES.MODE_CTR, nonce=nonce)
    flag = cipher.decrypt(encrypted_flag).decode()

    print(f"[+] Recovered flag: {flag}")

    with open("/app/flag.txt", "w") as f:
        f.write(flag)
    print("[+] Flag written to /app/flag.txt")
    return flag


def evaluate_patches():
    """
    Evaluate proposed security patches against the MT19937 state recovery attack.

    The core vulnerability: the calibration log leaks 624 consecutive MT19937
    outputs, which is exactly the internal state size. An attacker can untemper
    these outputs to fully reconstruct the PRNG state, then replay subsequent
    PRNG calls to recover all key material.

    Patch A (PRNG desynchronization): INEFFECTIVE.
    Inserting N dummy getrandbits() calls between calibration and key generation
    does NOT prevent the attack. Once the attacker has the full MT19937 state,
    they can advance the cloned PRNG by the same N steps (the count is in the
    source code). Even if the count were secret, the attacker could brute-force
    it by checking generated n = p*q against the known public RSA modulus.
    MT19937 is fully deterministic; knowing the state means knowing ALL future
    outputs regardless of how many are skipped.

    Patch B (CSPRNG key isolation): EFFECTIVE.
    Replacing rng.getrandbits() with os.urandom() for key generation completely
    severs the dependency between the leaked MT19937 state and the key material.
    Even with a perfect clone of the calibration PRNG, no information about the
    RSA primes, AES key, or nonce can be derived because they come from the
    kernel's CSPRNG (/dev/urandom), which has independent entropy.

    Patch C (seed hardening via PBKDF2): INEFFECTIVE.
    PBKDF2 strengthens the seed-to-state mapping, making it computationally
    infeasible to brute-force the original master secret. However, the attack
    does NOT target the seed at all. The attack recovers the PRNG's internal
    state directly from the 624 leaked outputs via untempering, completely
    bypassing the seeding mechanism. A stronger seed provides zero additional
    protection when the full internal state is already leaked. This patch
    addresses the wrong threat model.
    """
    assessment = {
        "patch_a": {
            "effective": False,
            "justification": (
                "PRNG state desynchronization is ineffective. After recovering "
                "the full MT19937 state from 624 calibration outputs, an attacker "
                "can advance the cloned PRNG by the same number of dummy rounds "
                "(visible in source code) to resynchronize with key generation. "
                "Even if the round count were secret, it could be brute-forced by "
                "checking each candidate against the known RSA public modulus. "
                "MT19937 is fully deterministic: knowing the state means knowing "
                "all future outputs regardless of how many are consumed."
            ),
        },
        "patch_b": {
            "effective": True,
            "justification": (
                "CSPRNG key isolation is effective. By generating all RSA primes, "
                "AES keys, and nonces from os.urandom() (backed by /dev/urandom), "
                "key material becomes completely independent of the MT19937 PRNG "
                "state. Even with a perfect clone of the calibration PRNG, no "
                "information about the cryptographic keys can be derived because "
                "they originate from the kernel's CSPRNG with independent entropy. "
                "The calibration log becomes harmless."
            ),
        },
        "patch_c": {
            "effective": False,
            "justification": (
                "Seed hardening via PBKDF2 is ineffective. While PBKDF2 makes "
                "brute-force seed recovery computationally infeasible, the actual "
                "attack does not target the seed. The attack recovers the MT19937 "
                "internal state directly from the 624 leaked calibration outputs "
                "via untempering, completely bypassing the seeding mechanism. "
                "Regardless of how the PRNG was seeded, once 624 consecutive "
                "outputs are observed, the full state is recoverable. This patch "
                "addresses the wrong threat model (seed guessing vs. state leakage)."
            ),
        },
    }

    with open("/app/patch_assessment.json", "w") as f:
        json.dump(assessment, f, indent=2)
    print("[+] Patch assessment written to /app/patch_assessment.json")


def main():
    recover_flag()
    print()
    evaluate_patches()


if __name__ == "__main__":
    main()
