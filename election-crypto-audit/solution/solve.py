#!/usr/bin/env python3

"""
Solution for the election cryptosystem audit & remediation assessment task.

Phase 1: Exploits three RSA key generation vulnerabilities to decrypt all ballots.
  - Batch alpha: GCD attack on shared prime factors from pool-based generation
  - Batch beta: PRNG seed reproduction from audit log timestamps
  - Batch gamma: Fermat factorization on close primes from adjacent derivation

Phase 2: Evaluates five proposed patches for security by analyzing code and
  attempting attacks on test keys.
"""

import json
import math
import hashlib
import hmac
import random
import re
import os
import sqlite3
import subprocess
import sys

sys.path.insert(0, '/app')
from election_system import _next_prime, RSA_HALF_BITS, PUBLIC_EXPONENT


# ======================================================================
# PEM key parsing via openssl
# ======================================================================

def extract_modulus(pem_path):
    """Extract RSA modulus from a PEM public key file using openssl."""
    result = subprocess.run(
        ['openssl', 'rsa', '-pubin', '-in', pem_path, '-modulus', '-noout'],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"openssl failed for {pem_path}: {result.stderr}")
    for line in result.stdout.strip().split('\n'):
        if line.startswith('Modulus='):
            return int(line.split('=', 1)[1], 16)
    raise RuntimeError(f"Could not parse modulus from {pem_path}")


# ======================================================================
# SQLite data loading
# ======================================================================

def load_election_data(db_path='/app/election.db'):
    """Load voter data and encrypted ballots from SQLite database."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT value FROM election_meta WHERE key='candidates'")
    candidates = json.loads(cur.fetchone()[0])

    cur.execute("""
        SELECT v.voter_id, v.batch, b.encrypted_vote
        FROM voters v JOIN ballots b ON v.voter_id = b.voter_id
        ORDER BY v.voter_id
    """)
    voters = []
    for row in cur.fetchall():
        voters.append({
            'voter_id': row[0],
            'batch': row[1],
            'encrypted_vote': int(row[2])
        })

    conn.close()
    return candidates, voters


# ======================================================================
# RSA math utilities
# ======================================================================

def _extended_gcd(a, b):
    if a == 0:
        return b, 0, 1
    g, x, y = _extended_gcd(b % a, a)
    return g, y - (b // a) * x, x


def _modinv(a, m):
    g, x, _ = _extended_gcd(a % m, m)
    if g != 1:
        raise ValueError(f"No modular inverse for {a} mod {m}")
    return x % m


def rsa_decrypt(c, p, q, e=PUBLIC_EXPONENT):
    """Decrypt RSA ciphertext given the prime factors."""
    phi = (p - 1) * (q - 1)
    d = _modinv(e, phi)
    n = p * q
    return pow(c, d, n)


def decode_vote(m, voter_id):
    """Decode vote from RSA plaintext, verifying HMAC binding."""
    msg_bytes = m.to_bytes(33, 'big')
    expected_tag = hmac.new(
        voter_id.encode(), b"securevote_ballot_v2", hashlib.sha256
    ).digest()
    if msg_bytes[:32] != expected_tag:
        raise ValueError(f"HMAC verification failed for {voter_id}")
    return msg_bytes[-1]


# ======================================================================
# Factoring attacks
# ======================================================================

def fermat_factor(n, max_iter=10_000_000):
    """Fermat factorization — efficient when |p - q| is small."""
    a = math.isqrt(n)
    if a * a == n:
        return a, a
    a += 1
    for _ in range(max_iter):
        b_sq = a * a - n
        b = math.isqrt(b_sq)
        if b * b == b_sq:
            p, q = a + b, a - b
            if p > 1 and q > 1:
                return p, q
        a += 1
    return None


# ======================================================================
# Phase 1: Decrypt all ballots
# ======================================================================

def decrypt_all_ballots(candidates, voters):
    """Decrypt all 30 ballots using three different attacks."""
    print("Loading RSA moduli from PEM files...")
    moduli = {}
    for v in voters:
        vid = v['voter_id']
        moduli[vid] = extract_modulus(f'/app/keys/{vid}.pem')

    print("Parsing audit log for key generation parameters...")
    with open('/app/audit.log') as f:
        audit_log = f.read()

    results = {}

    # --- Attack 1: Batch alpha — GCD on shared prime factors ---
    print("\n[Attack 1] Batch alpha: GCD on shared prime factors")
    alpha = [v for v in voters if v['batch'] == 'alpha']
    alpha_moduli = {v['voter_id']: moduli[v['voter_id']] for v in alpha}

    for v in alpha:
        vid = v['voter_id']
        n_i = alpha_moduli[vid]
        shared = None
        for vid2, n_j in alpha_moduli.items():
            if vid2 != vid:
                g = math.gcd(n_i, n_j)
                if 1 < g < n_i:
                    shared = g
                    break
        if shared is None:
            raise RuntimeError(f"No shared factor for {vid}")
        p = shared
        q = n_i // p
        m = rsa_decrypt(v['encrypted_vote'], p, q)
        results[vid] = candidates[decode_vote(m, vid)]
        print(f"  {vid}: {results[vid]}")

    # --- Attack 2: Batch beta — PRNG seed reproduction ---
    print("\n[Attack 2] Batch beta: PRNG seed reproduction from audit log")
    beta = [v for v in voters if v['batch'] == 'beta']
    seed_times = {}
    for line in audit_log.split('\n'):
        match = re.search(
            r'KeyGen voter=(V\d+) batch=beta.*seed_time=(\d+)', line
        )
        if match:
            seed_times[match.group(1)] = int(match.group(2))

    for v in beta:
        vid = v['voter_id']
        ts = seed_times[vid]
        rng = random.Random(ts)
        p_bits = rng.getrandbits(RSA_HALF_BITS)
        p_bits |= (1 << (RSA_HALF_BITS - 1)) | 1
        p = _next_prime(p_bits)
        q_bits = rng.getrandbits(RSA_HALF_BITS)
        q_bits |= (1 << (RSA_HALF_BITS - 1)) | 1
        q = _next_prime(q_bits)
        if p * q != moduli[vid]:
            raise RuntimeError(f"Key reproduction failed for {vid}")
        m = rsa_decrypt(v['encrypted_vote'], p, q)
        results[vid] = candidates[decode_vote(m, vid)]
        print(f"  {vid}: {results[vid]}")

    # --- Attack 3: Batch gamma — Fermat factorization ---
    print("\n[Attack 3] Batch gamma: Fermat factorization (close primes)")
    gamma = [v for v in voters if v['batch'] == 'gamma']
    for v in gamma:
        vid = v['voter_id']
        n = moduli[vid]
        factored = fermat_factor(n)
        if factored is None:
            raise RuntimeError(f"Fermat factorization failed for {vid}")
        p, q = factored
        if p * q != n:
            raise RuntimeError(f"Factoring verification failed for {vid}")
        m = rsa_decrypt(v['encrypted_vote'], p, q)
        results[vid] = candidates[decode_vote(m, vid)]
        print(f"  {vid}: {results[vid]}")

    return results


# ======================================================================
# Phase 2: Evaluate proposed patches
# ======================================================================

def get_test_moduli(patch_name):
    """Load test key moduli for a patch from PEM files using openssl."""
    dir_path = f'/app/patches/test_keys/{patch_name}'
    moduli = []
    for fname in sorted(os.listdir(dir_path)):
        if fname.endswith('.pem'):
            moduli.append(extract_modulus(os.path.join(dir_path, fname)))
    return moduli


def try_pool_reproduction(patch_code, test_moduli):
    """Try to factor test keys by reproducing a deterministic prime pool."""
    seed_match = re.search(r'batch_seed\s*=\s*(0x[0-9A-Fa-f]+)', patch_code)
    if not seed_match:
        return False
    seed = int(seed_match.group(1), 16)

    mult_match = re.search(r'pool_size\s*=\s*count\s*\*\s*(\d+)', patch_code)
    mult = int(mult_match.group(1)) if mult_match else 3

    count = len(test_moduli)
    pool_size = count * mult

    rng = random.Random(seed)
    prime_pool = []
    for _ in range(pool_size):
        candidate = rng.getrandbits(RSA_HALF_BITS)
        candidate |= (1 << (RSA_HALF_BITS - 1)) | 1
        prime_pool.append(_next_prime(candidate))

    for n in test_moduli:
        found = False
        for p in prime_pool:
            if p > 1 and n % p == 0:
                q = n // p
                if q > 1:
                    found = True
                    break
        if not found:
            return False
    return True


def evaluate_patches():
    """Evaluate each patch's security by analyzing code and testing keys."""
    verdicts = {}

    for patch_name in ['A', 'B', 'C', 'D', 'E']:
        print(f"\n  Evaluating patch {patch_name}...")
        test_moduli = get_test_moduli(patch_name)
        with open(f'/app/patches/patch_{patch_name}.py') as f:
            patch_code = f.read()

        verdict = "SECURE"

        # Strategy 1: Pairwise GCD between test keys
        for i in range(len(test_moduli)):
            for j in range(i + 1, len(test_moduli)):
                g = math.gcd(test_moduli[i], test_moduli[j])
                if 1 < g < test_moduli[i]:
                    verdict = "VULNERABLE"
                    print(f"    -> GCD attack succeeded on test keys {i+1},{j+1}")
                    break
            if verdict != "SECURE":
                break

        # Strategy 2: Fermat factorization (limited iterations)
        if verdict == "SECURE":
            for idx, n in enumerate(test_moduli):
                result = fermat_factor(n, max_iter=2_000_000)
                if result is not None:
                    verdict = "VULNERABLE"
                    print(f"    -> Fermat factorization succeeded on test key {idx+1}")
                    break

        # Strategy 3: Deterministic pool reproduction from embedded seed
        if verdict == "SECURE":
            if try_pool_reproduction(patch_code, test_moduli):
                verdict = "VULNERABLE"
                print(f"    -> Pool reproduction attack succeeded")

        if verdict == "SECURE":
            print(f"    -> All attacks failed: SECURE")

        verdicts[patch_name] = verdict

    return verdicts


# ======================================================================
# Main
# ======================================================================

def main():
    print("=" * 60)
    print("Phase 1: Decrypting ballots")
    print("=" * 60)
    candidates, voters = load_election_data()
    votes = decrypt_all_ballots(candidates, voters)

    tally = {c: 0 for c in candidates}
    for choice in votes.values():
        tally[choice] += 1

    print(f"\nDecrypted {len(votes)}/30 votes")
    print(f"Tally: {json.dumps(tally)}")

    print("\n" + "=" * 60)
    print("Phase 2: Evaluating proposed remediations")
    print("=" * 60)
    patch_verdicts = evaluate_patches()

    print(f"\nPatch verdicts: {json.dumps(patch_verdicts)}")

    output = {
        'tally': tally,
        'votes': votes,
        'patch_assessment': patch_verdicts,
    }

    with open('/app/results.json', 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nResults written to /app/results.json")


if __name__ == '__main__':
    main()
