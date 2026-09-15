#!/usr/bin/env python3
"""
RSA Vault Attack Script
========================
Extracts RSA public keys from multiple formats (PEM certs, DER keys, PCAP
captures, PGP keys), breaks weak keys using various factoring attacks,
decrypts Shamir shares, and reconstructs the master secret.

"""

import json
import math
import sys
import subprocess
import struct
import base64
import re
import os


def load_manifest():
    with open("/app/vault_manifest.json") as f:
        return json.load(f)


def gcd(a, b):
    while b:
        a, b = b, a % b
    return a


def extended_gcd(a, b):
    if a == 0:
        return b, 0, 1
    g, x, y = extended_gcd(b % a, a)
    return g, y - (b // a) * x, x


def modinv(a, m):
    g, x, _ = extended_gcd(a % m, m)
    if g != 1:
        raise ValueError(f"No modular inverse for {a} mod {m}")
    return x % m


def isqrt(n):
    if n < 0:
        raise ValueError("Square root of negative number")
    if n == 0:
        return 0
    x = n
    y = (x + 1) // 2
    while y < x:
        x = y
        y = (x + n // x) // 2
    return x


def is_perfect_square(n):
    s = isqrt(n)
    return s * s == n


# ============================================================
# Key Extraction from Multiple Formats
# ============================================================

def extract_key_from_pem_cert(pem_path):
    """Extract RSA modulus and exponent from X.509 PEM certificate."""
    print(f"[openssl] Extracting key from certificate: {pem_path}")

    result = subprocess.run(
        ["openssl", "x509", "-text", "-noout", "-in", pem_path],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        n, e = parse_openssl_rsa_output(result.stdout)
        if n and e:
            print(f"  Extracted via openssl: n={n.bit_length()} bits, e={e}")
            return n, e

    print("  Falling back to manual PEM parsing...")
    return extract_key_from_pem_manual(pem_path)


def extract_key_from_der(der_path):
    """Extract RSA modulus and exponent from DER-encoded public key."""
    print(f"[der] Extracting key from DER file: {der_path}")

    # Try openssl rsa
    result = subprocess.run(
        ["openssl", "rsa", "-pubin", "-inform", "DER", "-text", "-noout",
         "-in", der_path],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        n, e = parse_openssl_rsa_output(result.stdout)
        if n and e:
            print(f"  Extracted via openssl: n={n.bit_length()} bits, "
                  f"e={e if e.bit_length() < 64 else f'{e.bit_length()} bits'}")
            return n, e

    # Try openssl pkey
    result2 = subprocess.run(
        ["openssl", "pkey", "-pubin", "-inform", "DER", "-text", "-noout",
         "-in", der_path],
        capture_output=True, text=True
    )
    if result2.returncode == 0:
        n, e = parse_openssl_rsa_output(result2.stdout)
        if n and e:
            print(f"  Extracted via openssl pkey: n={n.bit_length()} bits")
            return n, e

    # Fallback: manual DER parsing
    print("  Falling back to manual DER parsing...")
    return extract_key_from_der_manual(der_path)


def extract_key_and_share_from_pcap(pcap_path):
    """Extract RSA key and encrypted share from PCAP capture."""
    print(f"[pcap] Extracting data from PCAP: {pcap_path}")

    payloads = []

    # Try tshark first
    try:
        result = subprocess.run(
            ["tshark", "-r", pcap_path, "-T", "fields", "-e", "data"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().split('\n'):
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = bytes.fromhex(line.replace(':', ''))
                    text = raw.decode('utf-8', errors='replace')
                    if '{' in text and '}' in text:
                        start = text.index('{')
                        end = text.rindex('}') + 1
                        payloads.append(json.loads(text[start:end]))
                except (ValueError, json.JSONDecodeError):
                    continue
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: manual PCAP parsing
    if not payloads:
        print("  Using manual PCAP parser...")
        payloads = parse_pcap_manual(pcap_path)

    n, e, encrypted_share = None, None, None
    for payload in payloads:
        if payload.get("type") == "KEY_EXCHANGE":
            pk = payload.get("public_key", {})
            n = int(pk["n"])
            e = int(pk["e"])
            print(f"  Found key: n={n.bit_length()} bits, e={e}")
        elif payload.get("type") == "ENCRYPTED_SHARE_TRANSFER":
            encrypted_share = int(payload["encrypted_share"])
            print(f"  Found encrypted share: {encrypted_share.bit_length()} bits")

    return n, e, encrypted_share


def extract_key_from_pgp(pgp_path):
    """Extract RSA key parameters from PGP public key."""
    print(f"[pgp] Extracting key from PGP file: {pgp_path}")
    n, e = parse_pgp_manual(pgp_path)
    print(f"  RSA n: {n.bit_length()} bits, e: {e}")
    return n, e


# ============================================================
# Parsers
# ============================================================

def parse_openssl_rsa_output(output):
    """Parse modulus and exponent from openssl text output."""
    lines = output.split('\n')
    modulus_hex = ""
    exponent = None
    in_modulus = False

    for line in lines:
        stripped = line.strip()

        if re.match(r'(?i)^(public-key.*)?modulus:', stripped) or \
           stripped.lower().startswith('modulus:'):
            in_modulus = True
            parts = stripped.split(':', 1)
            rest = parts[-1].strip() if len(parts) > 1 else ''
            if rest and re.match(r'^[0-9a-f:]+', rest):
                modulus_hex += rest
            continue

        if re.match(r'(?i)^exponent:', stripped):
            in_modulus = False
            match = re.search(r'Exponent:\s*(\d+)\s*\(', stripped,
                              re.IGNORECASE)
            if match:
                exponent = int(match.group(1))
            else:
                # Large exponent: openssl displays as hex
                parts = stripped.split(':', 1)
                rest = parts[-1].strip() if len(parts) > 1 else ''
                match2 = re.search(r'(\d+)', rest)
                if match2:
                    exponent = int(match2.group(1))
            continue

        if in_modulus:
            if stripped and re.match(r'^[0-9a-f][0-9a-f:]*', stripped):
                modulus_hex += stripped
            else:
                in_modulus = False

    modulus_hex = modulus_hex.replace(':', '').replace(' ', '').strip()
    if modulus_hex.startswith('00'):
        modulus_hex = modulus_hex[2:]
    n = int(modulus_hex, 16) if modulus_hex else None

    return n, exponent


def extract_key_from_pem_manual(pem_path):
    """Parse RSA public key from PEM certificate by decoding DER."""
    with open(pem_path) as f:
        pem = f.read()
    lines = pem.strip().split('\n')
    b64 = ''.join(l for l in lines if not l.startswith('-----'))
    der = base64.b64decode(b64)
    return extract_rsa_from_der_bytes(der)


def extract_key_from_der_manual(der_path):
    """Parse RSA public key from DER file."""
    with open(der_path, 'rb') as f:
        der = f.read()
    return extract_rsa_from_der_bytes(der)


def extract_rsa_from_der_bytes(der):
    """Extract RSA n, e from DER-encoded SubjectPublicKeyInfo or Certificate."""
    for i in range(len(der) - 3):
        if der[i] == 0x03:  # BIT STRING
            if der[i+1] < 0x80:
                data_start = i + 2
            elif der[i+1] == 0x81:
                data_start = i + 3
            elif der[i+1] == 0x82:
                data_start = i + 4
            else:
                continue

            if data_start < len(der) and der[data_start] == 0x00:
                if data_start + 1 < len(der) and der[data_start + 1] == 0x30:
                    seq_start = data_start + 1
                    return parse_rsa_sequence(der, seq_start)
    return None, None


def parse_rsa_sequence(der, offset):
    """Parse SEQUENCE { INTEGER n, INTEGER e } from DER."""
    if der[offset] != 0x30:
        return None, None
    offset += 1
    if der[offset] < 0x80:
        offset += 1
    elif der[offset] == 0x81:
        offset += 2
    elif der[offset] == 0x82:
        offset += 3

    n, offset = parse_der_integer(der, offset)
    e, offset = parse_der_integer(der, offset)
    return n, e


def parse_der_integer(der, offset):
    """Parse a DER INTEGER."""
    if der[offset] != 0x02:
        return None, offset
    offset += 1
    if der[offset] < 0x80:
        length = der[offset]
        offset += 1
    elif der[offset] == 0x81:
        length = der[offset + 1]
        offset += 2
    elif der[offset] == 0x82:
        length = (der[offset + 1] << 8) | der[offset + 2]
        offset += 3
    else:
        return None, offset

    int_bytes = der[offset:offset + length]
    value = int.from_bytes(int_bytes, 'big')
    return value, offset + length


def parse_pcap_manual(pcap_path):
    """Manually parse PCAP file to extract UDP payloads."""
    with open(pcap_path, 'rb') as f:
        data = f.read()

    offset = 24  # skip global header
    payloads = []

    while offset < len(data) - 16:
        ts_sec, ts_usec, incl_len, orig_len = struct.unpack(
            '<IIII', data[offset:offset+16])
        offset += 16
        pkt = data[offset:offset+incl_len]
        offset += incl_len

        # Skip Ethernet (14) + IP (20) + UDP (8) = 42 bytes
        if len(pkt) > 42:
            payload_bytes = pkt[42:]
            try:
                text = payload_bytes.decode('utf-8')
                start = text.index('{')
                end = text.rindex('}') + 1
                payload = json.loads(text[start:end])
                payloads.append(payload)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                pass

    return payloads


def parse_pgp_manual(pgp_path):
    """Parse PGP public key file to extract RSA MPI values."""
    with open(pgp_path) as f:
        content = f.read()

    lines = content.strip().split('\n')
    b64_lines = []
    started = False
    for line in lines:
        if line == '':
            started = True
            continue
        if line.startswith('='):
            break
        if started:
            b64_lines.append(line)

    data = base64.b64decode(''.join(b64_lines))

    tag_byte = data[0]
    length_type = tag_byte & 0x03

    if length_type == 0:
        body_start = 2
    elif length_type == 1:
        body_start = 3
    elif length_type == 2:
        body_start = 5
    else:
        raise ValueError("Indeterminate length not supported")

    body = data[body_start:]

    # Version 4: version(1) + creation_time(4) + algorithm(1) + MPIs
    mpi_offset = 6

    n_bits = struct.unpack('>H', body[mpi_offset:mpi_offset+2])[0]
    n_bytes_len = (n_bits + 7) // 8
    n = int.from_bytes(body[mpi_offset+2:mpi_offset+2+n_bytes_len], 'big')
    mpi_offset += 2 + n_bytes_len

    e_bits = struct.unpack('>H', body[mpi_offset:mpi_offset+2])[0]
    e_bytes_len = (e_bits + 7) // 8
    e = int.from_bytes(body[mpi_offset+2:mpi_offset+2+e_bytes_len], 'big')

    return n, e


# ============================================================
# RSA Attacks
# ============================================================

def attack_shared_factor(keys_list):
    """Find shared prime factors between any pair of moduli."""
    results = {}
    for i in range(len(keys_list)):
        for j in range(i + 1, len(keys_list)):
            id_i, n_i = keys_list[i]
            id_j, n_j = keys_list[j]
            g = gcd(n_i, n_j)
            if g > 1 and g < n_i and g < n_j:
                print(f"[GCD] Keys {id_i} and {id_j} share factor "
                      f"({g.bit_length()} bits)")
                results[id_i] = (g, n_i // g)
                results[id_j] = (g, n_j // g)
    return results


def attack_fermat(n, max_iterations=100000):
    """Factor n when p and q are close together."""
    a = isqrt(n)
    if a * a < n:
        a += 1
    for i in range(max_iterations):
        b2 = a * a - n
        if b2 >= 0 and is_perfect_square(b2):
            b = isqrt(b2)
            p = a + b
            q = a - b
            if p * q == n and p > 1 and q > 1:
                print(f"[Fermat] Factored at iteration {i}: diff={p-q}")
                return (min(p, q), max(p, q))
        a += 1
    return None


def continued_fraction(e, n):
    cf = []
    while n:
        q = e // n
        cf.append(q)
        e, n = n, e - q * n
    return cf


def convergents(cf):
    h_prev, h_curr = 0, 1
    k_prev, k_curr = 1, 0
    for a in cf:
        h_prev, h_curr = h_curr, a * h_curr + h_prev
        k_prev, k_curr = k_curr, a * k_curr + k_prev
        yield h_curr, k_curr


def attack_wiener(n, e):
    """Wiener's attack: recover d when d < N^(1/4) / 3."""
    cf = continued_fraction(e, n)
    for k, d in convergents(cf):
        if k == 0:
            continue
        if (e * d - 1) % k != 0:
            continue
        phi = (e * d - 1) // k
        s = n - phi + 1
        discriminant = s * s - 4 * n
        if discriminant < 0:
            continue
        if is_perfect_square(discriminant):
            sqrt_d = isqrt(discriminant)
            p = (s + sqrt_d) // 2
            q = (s - sqrt_d) // 2
            if p * q == n:
                print(f"[Wiener] Found d={d} ({d.bit_length()} bits)")
                return (min(p, q), max(p, q), d)
    return None


def sieve_primes(limit):
    """Sieve of Eratosthenes."""
    is_p = [True] * (limit + 1)
    is_p[0] = is_p[1] = False
    for i in range(2, int(limit**0.5) + 1):
        if is_p[i]:
            for j in range(i*i, limit + 1, i):
                is_p[j] = False
    return [i for i in range(2, limit + 1) if is_p[i]]


def attack_pollard_p1(n, B=2**18):
    """Pollard's p-1 factoring: works when p-1 is B-smooth."""
    primes = sieve_primes(B)
    a = 2
    for p in primes:
        pp = p
        while pp * p <= B:
            pp *= p
        a = pow(a, pp, n)
        g = gcd(a - 1, n)
        if 1 < g < n:
            print(f"[Pollard p-1] Found factor at prime {p}")
            return (g, n // g)
    return None


def pollard_rho_with_c(n, c):
    x = 2
    y = 2
    d = 1
    f = lambda x: (x * x + c) % n
    count = 0
    while d == 1:
        x = f(x)
        y = f(f(y))
        d = gcd(abs(x - y), n)
        if x == y:
            return None
        count += 1
        if count > 1000000:
            return None
    return d if d != n else None


def is_prime_miller_rabin(n, k=20):
    if n < 2:
        return False
    if n == 2 or n == 3:
        return True
    if n % 2 == 0:
        return False
    r, d = 0, n - 1
    while d % 2 == 0:
        r += 1
        d //= 2
    import random
    rng = random.Random(42)
    for _ in range(k):
        a = rng.randrange(2, n - 1)
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


def factor_completely(n):
    """Factor n completely into prime factors."""
    factors = []
    for p in range(2, min(2**20, isqrt(n) + 1)):
        while n % p == 0:
            factors.append(p)
            n //= p
    if n == 1:
        return factors

    stack = [n]
    while stack:
        num = stack.pop()
        if num == 1:
            continue
        if is_prime_miller_rabin(num):
            factors.append(num)
            continue
        d = None
        for c in range(1, 200):
            d = pollard_rho_with_c(num, c)
            if d and d != num:
                break
        if d and d != num:
            stack.append(d)
            stack.append(num // d)
        else:
            factors.append(num)
    return sorted(factors)


# ============================================================
# Shamir's Secret Sharing Reconstruction
# ============================================================

def shamir_reconstruct(shares, prime):
    secret = 0
    for i, (xi, yi) in enumerate(shares):
        num = 1
        den = 1
        for j, (xj, _) in enumerate(shares):
            if i != j:
                num = (num * (-xj)) % prime
                den = (den * (xi - xj)) % prime
        lagrange = (num * pow(den, -1, prime)) % prime
        secret = (secret + yi * lagrange) % prime
    return secret


# ============================================================
# Main Attack Orchestration
# ============================================================

def main():
    manifest = load_manifest()
    prime = int(manifest["sss_prime"])
    threshold = manifest["threshold"]
    parties = manifest["parties"]

    print(f"Loaded vault manifest: {len(parties)} parties, threshold={threshold}")
    print(f"SSS prime: {prime} ({prime.bit_length()} bits)")
    print()

    # ===== Step 1: Extract keys and shares from all formats =====
    print("=" * 60)
    print("STEP 1: Extract RSA public keys from multiple formats")
    print("=" * 60)

    party_data = {}

    for party in parties:
        pid = party["id"]
        key_format = party["key_format"]
        print(f"\n--- Party {pid} ({party['name']}): {key_format} ---")

        n, e = None, None
        c = None

        if key_format == "x509_pem_certificate":
            n, e = extract_key_from_pem_cert(party["key_location"])
            with open(party["share_location"]) as f:
                c = int(f.read().strip())

        elif key_format == "der_pkcs8_public_key":
            n, e = extract_key_from_der(party["key_location"])
            with open(party["share_location"]) as f:
                c = int(f.read().strip())

        elif key_format == "network_capture":
            n, e, c = extract_key_and_share_from_pcap(party["key_location"])

        elif key_format == "pgp_public_key":
            n, e = extract_key_from_pgp(party["key_location"])
            with open(party["share_location"]) as f:
                c = int(f.read().strip())

        else:
            print(f"  Unknown format: {key_format}")
            continue

        if n is None or e is None:
            print(f"  WARNING: Failed to extract key for party {pid}")
            continue

        party_data[pid] = {"n": n, "e": e, "encrypted_share": c}
        print(f"  n: {n.bit_length()} bits")
        if e.bit_length() < 64:
            print(f"  e: {e}")
        else:
            print(f"  e: {e.bit_length()} bits (large exponent)")
        print(f"  encrypted_share: {c.bit_length()} bits")

    print(f"\nExtracted keys for {len(party_data)} / {len(parties)} parties")

    # ===== Step 2: Apply RSA attacks =====
    print("\n" + "=" * 60)
    print("STEP 2: Attack RSA keys")
    print("=" * 60)

    factored = {}

    # --- GCD shared factor ---
    print("\n--- GCD Shared Factor Attack ---")
    moduli_list = [(pid, party_data[pid]["n"])
                   for pid in sorted(party_data.keys())]
    gcd_results = attack_shared_factor(moduli_list)
    for pid, (p, q) in gcd_results.items():
        e = party_data[pid]["e"]
        phi = (p - 1) * (q - 1)
        d = modinv(e, phi)
        factored[pid] = ([p, q], d)
        print(f"  Key {pid}: factored via GCD")

    # --- Fermat (close primes) ---
    print("\n--- Fermat's Factorization ---")
    for pid in sorted(party_data.keys()):
        if pid in factored:
            continue
        n = party_data[pid]["n"]
        e = party_data[pid]["e"]
        result = attack_fermat(n)
        if result:
            p, q = result
            phi = (p - 1) * (q - 1)
            d = modinv(e, phi)
            factored[pid] = ([p, q], d)
            print(f"  Key {pid}: factored via Fermat")

    # --- Wiener (small d / large e) ---
    print("\n--- Wiener's Attack ---")
    for pid in sorted(party_data.keys()):
        if pid in factored or len(factored) >= threshold:
            continue
        n = party_data[pid]["n"]
        e = party_data[pid]["e"]
        # Try Wiener if e is unusually large
        if e.bit_length() > n.bit_length() // 2:
            result = attack_wiener(n, e)
            if result:
                p, q, d = result
                factored[pid] = ([p, q], d)
                print(f"  Key {pid}: factored via Wiener")

    # --- Pollard p-1 ---
    if len(factored) < threshold:
        print("\n--- Pollard's p-1 Attack ---")
        for pid in sorted(party_data.keys()):
            if pid in factored or len(factored) >= threshold:
                continue
            n = party_data[pid]["n"]
            e = party_data[pid]["e"]
            result = attack_pollard_p1(n)
            if result:
                p, q = result
                phi = (p - 1) * (q - 1)
                d = modinv(e, phi)
                factored[pid] = ([p, q], d)
                print(f"  Key {pid}: factored via Pollard p-1")

    # --- Multi-prime factoring ---
    if len(factored) < threshold:
        print("\n--- Multi-prime Factoring ---")
        for pid in sorted(party_data.keys()):
            if pid in factored or len(factored) >= threshold:
                continue
            n = party_data[pid]["n"]
            e = party_data[pid]["e"]
            factors = factor_completely(n)
            if len(factors) > 1:
                product = 1
                for f in factors:
                    product *= f
                if product == n:
                    phi = 1
                    for f in factors:
                        phi *= (f - 1)
                    d = modinv(e, phi)
                    factored[pid] = (factors, d)
                    print(f"  Key {pid}: factored into {len(factors)} primes")

    print(f"\nFactored {len(factored)} / {len(party_data)} keys")
    if len(factored) < threshold:
        print(f"ERROR: Need at least {threshold} keys, only got {len(factored)}")
        sys.exit(1)

    # ===== Step 3: Decrypt shares =====
    print("\n" + "=" * 60)
    print("STEP 3: Decrypt shares and reconstruct secret")
    print("=" * 60)

    decrypted_shares = []
    for pid in sorted(factored.keys()):
        n = party_data[pid]["n"]
        c = party_data[pid]["encrypted_share"]
        _, d = factored[pid]
        m = pow(c, d, n)
        decrypted_shares.append((pid, m))
        print(f"  Share {pid}: {m}")

    shares_for_reconstruction = decrypted_shares[:threshold]
    print(f"\nReconstructing from {len(shares_for_reconstruction)} shares...")

    secret = shamir_reconstruct(shares_for_reconstruction, prime)
    secret_hex = format(secret, 'x')

    print(f"\nRecovered secret: {secret}")
    print(f"Recovered hex:    {secret_hex}")

    with open("/app/secret.txt", "w") as f:
        f.write(secret_hex)

    print(f"\nSecret written to /app/secret.txt")


if __name__ == "__main__":
    main()
