#!/usr/bin/env python3
"""
Full solution: recover private key from weak DH parameters and decrypt session.
"""
import base64
import hashlib
import math
import sqlite3
import struct


# ========== Artifact parsing ==========

def parse_der_length(data, offset):
    if data[offset] < 0x80:
        return data[offset], offset + 1
    num_bytes = data[offset] & 0x7F
    length = int.from_bytes(data[offset + 1:offset + 1 + num_bytes], "big")
    return length, offset + 1 + num_bytes


def parse_der_integer(data, offset):
    assert data[offset] == 0x02
    length, offset = parse_der_length(data, offset + 1)
    value = int.from_bytes(data[offset:offset + length], "big")
    return value, offset + length


def load_dh_params_from_pem(filepath):
    with open(filepath) as f:
        pem = f.read()
    b64 = "".join(
        l for l in pem.strip().split("\n") if not l.startswith("-----")
    )
    der = base64.b64decode(b64)
    assert der[0] == 0x30
    _, off = parse_der_length(der, 1)
    n, off = parse_der_integer(der, off)
    g, off = parse_der_integer(der, off)
    return n, g


def parse_binary_capture(filepath):
    with open(filepath, "rb") as f:
        data = f.read()
    off = 6  # magic(4) + version(2)
    off += 8  # timestamp
    sid_len = data[off]; off += 1
    session_id = data[off:off + sid_len].decode("ascii"); off += sid_len
    cipher_suite = data[off]; off += 1
    payload_len = struct.unpack(">I", data[off:off + 4])[0]; off += 4
    ciphertext = data[off:off + payload_len]; off += payload_len
    plaintext_hash = data[off:off + 32]
    return session_id, cipher_suite, ciphertext, plaintext_hash


def get_public_key(db_path, session_id):
    db = sqlite3.connect(db_path)
    cur = db.cursor()
    cur.execute(
        "SELECT public_value_hex FROM key_exchanges WHERE session_id = ?",
        (session_id,))
    row = cur.fetchone()
    db.close()
    return int(row[0], 16)


# ========== Factoring ==========

def pollard_p_minus_1(n, B=1000):
    a = 2
    for j in range(2, B + 1):
        a = pow(a, j, n)
    d = math.gcd(a - 1, n)
    if 1 < d < n:
        return d
    return None


def factor_n(n):
    for B in [100, 500, 1000, 5000, 10000]:
        p = pollard_p_minus_1(n, B)
        if p is not None:
            q = n // p
            assert p * q == n
            return min(p, q), max(p, q)
    raise RuntimeError("Could not factor n")


# ========== Smooth factorization ==========

def sieve_primes(limit):
    is_p = [True] * (limit + 1)
    is_p[0] = is_p[1] = False
    for i in range(2, int(limit ** 0.5) + 1):
        if is_p[i]:
            for j in range(i * i, limit + 1, i):
                is_p[j] = False
    return [i for i in range(2, limit + 1) if is_p[i]]


def factorize_smooth(n, primes):
    factors = {}
    for sp in primes:
        while n % sp == 0:
            factors[sp] = factors.get(sp, 0) + 1
            n //= sp
        if n == 1:
            break
    if n > 1:
        factors[n] = 1
    return factors


# ========== Pohlig-Hellman ==========

def baby_giant(g, h, p, order):
    m = int(math.isqrt(order)) + 1
    table = {}
    gj = 1
    for j in range(m):
        table[gj] = j
        gj = (gj * g) % p
    g_inv_m = pow(g, -m, p)
    gamma = h
    for i in range(m):
        if gamma in table:
            return (i * m + table[gamma]) % order
        gamma = (gamma * g_inv_m) % p
    return None


def pohlig_hellman(g, h, p, factor_dict):
    residues = []
    moduli = []
    for qi, ei in factor_dict.items():
        qi_ei = qi ** ei
        exp = (p - 1) // qi_ei
        gi = pow(g, exp, p)
        hi = pow(h, exp, p)
        xi = baby_giant(gi, hi, p, qi_ei)
        if xi is None:
            raise ValueError(f"BSGS failed for {qi}^{ei}")
        residues.append(xi)
        moduli.append(qi_ei)
    return crt_list(residues, moduli)


def crt_list(residues, moduli):
    M = 1
    for m in moduli:
        M *= m
    x = 0
    for ri, mi in zip(residues, moduli):
        Mi = M // mi
        yi = pow(Mi, -1, mi)
        x = (x + ri * Mi * yi) % M
    return x


def crt_general(a1, m1, a2, m2):
    d = math.gcd(m1, m2)
    if (a1 - a2) % d != 0:
        raise ValueError("No solution")
    lcm_val = m1 * m2 // d
    m1d = m1 // d
    m2d = m2 // d
    diff = (a2 - a1) // d
    t = (diff * pow(m1d, -1, m2d)) % m2d
    x = (a1 + m1 * t) % lcm_val
    return x


# ========== Main ==========

def main():
    print("[*] Loading artifacts...")
    n, g = load_dh_params_from_pem("/app/artifacts/server_dhparams.pem")
    session_id, cipher_suite, ciphertext, pt_hash = parse_binary_capture(
        "/app/artifacts/session_capture.bin")
    A = get_public_key("/app/artifacts/audit.db", session_id)

    print(f"[*] Modulus n = {n} ({n.bit_length()} bits)")
    print(f"[*] Generator g = {g}")
    print(f"[*] Session {session_id}, public key A = {A}")

    print("[*] Factoring modulus...")
    p, q = factor_n(n)
    print(f"[+] p = {p}")
    print(f"[+] q = {q}")

    primes = sieve_primes(10000)
    pm1f = factorize_smooth(p - 1, primes)
    qm1f = factorize_smooth(q - 1, primes)
    print(f"[+] p-1 factors: {pm1f}")
    print(f"[+] q-1 factors: {qm1f}")

    # Verify complete factorizations
    check = 1
    for b, e in pm1f.items():
        check *= b ** e
    assert check == p - 1, "Incomplete factorization of p-1"
    check = 1
    for b, e in qm1f.items():
        check *= b ** e
    assert check == q - 1, "Incomplete factorization of q-1"

    print("[*] Computing discrete log mod p...")
    a_mod_pm1 = pohlig_hellman(g % p, A % p, p, pm1f)
    print(f"[+] a mod (p-1) = {a_mod_pm1}")

    print("[*] Computing discrete log mod q...")
    a_mod_qm1 = pohlig_hellman(g % q, A % q, q, qm1f)
    print(f"[+] a mod (q-1) = {a_mod_qm1}")

    print("[*] Combining results...")
    a = crt_general(a_mod_pm1, p - 1, a_mod_qm1, q - 1)
    lam = (p - 1) * (q - 1) // math.gcd(p - 1, q - 1)
    a = a % lam
    print(f"[+] Recovered a = {a}")

    assert pow(g, a, n) == A, "Verification failed!"
    print("[+] Verified: g^a mod n == A")

    key = hashlib.sha256(str(a).encode()).digest()
    decrypted = bytes(
        ciphertext[i] ^ key[i % 32] for i in range(len(ciphertext))
    )
    plaintext = decrypted.decode("utf-8")
    print(f"[+] Decrypted: {plaintext}")

    with open("/app/private_key.txt", "w") as f:
        f.write(str(a))
    with open("/app/decrypted.txt", "w") as f:
        f.write(plaintext)

    print("[+] Done. Files written to /app/")


if __name__ == "__main__":
    main()
