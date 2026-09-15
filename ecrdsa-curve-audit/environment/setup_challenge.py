#!/usr/bin/env python3
"""Generate challenge data for ECC cross-algorithm nonce reuse forensics task."""
import json
import hashlib
import sys


def egcd(a, b):
    x0, x1, y0, y1 = 1, 0, 0, 1
    while b != 0:
        q, a, b = a // b, b, a % b
        x0, x1 = x1, x0 - q * x1
        y0, y1 = y1, y0 - q * y1
    return a, x0, y0


def modinv(a, m):
    g, x, _ = egcd(a % m, m)
    if g != 1:
        raise ValueError("No modular inverse")
    return x % m


def point_add(P, Q, curve_a, p):
    if P is None:
        return Q
    if Q is None:
        return P
    x1, y1 = P
    x2, y2 = Q
    if x1 == x2:
        if (y1 + y2) % p == 0:
            return None
        lam = ((3 * x1 * x1 + curve_a) * modinv(2 * y1, p)) % p
    else:
        lam = ((y2 - y1) * modinv((x2 - x1) % p, p)) % p
    x3 = (lam * lam - x1 - x2) % p
    y3 = (lam * (x1 - x3) - y1) % p
    return (x3, y3)


def scalar_mult(k, P, curve_a, p):
    R = None
    Q = P
    while k > 0:
        if k & 1:
            R = point_add(R, Q, curve_a, p)
        Q = point_add(Q, Q, curve_a, p)
        k >>= 1
    return R


def sha256_bytes(msg_str):
    return hashlib.sha256(msg_str.encode('utf-8')).digest()


def ecdsa_sign(msg, k, d, r_val, n):
    """ECDSA: s = k^-1 * (h + d*r) mod n"""
    h = int.from_bytes(sha256_bytes(msg), 'big') % n
    s = (modinv(k, n) * (h + d * r_val)) % n
    return s


def ecrdsa_rfc_sign(msg, k, d, r_val, n):
    """ECRDSA-RFC: s = r*d + k*e mod n, e from reversed hash bytes"""
    h_bytes = sha256_bytes(msg)
    h_int = int.from_bytes(h_bytes[::-1], 'big')
    e = h_int % n
    if e == 0:
        e = 1
    s = (r_val * d + k * e) % n
    return s


def ecrdsa_iso_sign(msg, k, d, r_val, n):
    """ECRDSA-ISO: s = r*d + k*e mod n, e from big-endian hash"""
    h_bytes = sha256_bytes(msg)
    h_int = int.from_bytes(h_bytes, 'big')
    e = h_int % n
    if e == 0:
        e = 1
    s = (r_val * d + k * e) % n
    return s


def ecdsa_verify(msg, r, s, Q, G, a_coeff, p, n):
    h = int.from_bytes(sha256_bytes(msg), 'big') % n
    si = modinv(s, n)
    u = (si * h) % n
    v = (si * r) % n
    W = point_add(scalar_mult(u, G, a_coeff, p), scalar_mult(v, Q, a_coeff, p), a_coeff, p)
    if W is None:
        return False
    return W[0] % n == r


def ecrdsa_verify(msg, r, s, Q, G, a_coeff, p, n, iso):
    hb = sha256_bytes(msg)
    h_int = int.from_bytes(hb, 'big') if iso else int.from_bytes(hb[::-1], 'big')
    e = h_int % n
    if e == 0:
        e = 1
    ei = modinv(e, n)
    u = (ei * s) % n
    v = (-ei * r) % n
    W = point_add(scalar_mult(u, G, a_coeff, p), scalar_mult(v, Q, a_coeff, p), a_coeff, p)
    if W is None:
        return False
    return W[0] % n == r


def main():
    # FRP256V1 curve parameters
    p = 0xF1FD178C0B3AD58F10126DE8CE42435B3961ADBCABC8CA6DE8FCF353D86E9C03
    a = 0xF1FD178C0B3AD58F10126DE8CE42435B3961ADBCABC8CA6DE8FCF353D86E9C00
    b = 0xEE353FCA5428A9300D4ABA754A44C00FDFEC0C9AE4B1A1803075ED967B7BB73F
    Gx = 0xB6B3D4C356C139EB31183D4749D423958C27D2DCAF98B70164C97A2DD98F5CFF
    Gy = 0x6142E0F7C8B204911F9271F0F3ECEF8C2701C307E8E4C9E183115A1554062CFB
    n = 0xF1FD178C0B3AD58F10126DE8CE42435B53DC67E140D2BF941FFDD459C6D655E1
    G = (Gx, Gy)

    assert pow(Gy, 2, p) == (pow(Gx, 3, p) + a * Gx + b) % p

    d = 0x7A32849E569C8888F25DE6F69A839D75057383F473ACF559ABD3C5D683294CE3
    assert 0 < d < n
    Q = scalar_mult(d, G, a, p)
    assert pow(Q[1], 2, p) == (pow(Q[0], 3, p) + a * Q[0] + b) % p

    def make_nonce(label):
        k_raw = int.from_bytes(hashlib.sha256(label.encode()).digest(), 'big')
        return k_raw % (n - 1) + 1

    # The SHARED nonce — used in sig 0 (ECDSA) and sig 3 (ECRDSA-RFC)
    k_shared = make_nonce("nonce_shared_alpha")

    # Signature specifications: (message, algorithm, nonce)
    sigs_spec = [
        ("Transaction alpha confirmed at 14:32 UTC", "ecdsa", k_shared),
        ("Audit log entry: session 7f3a started", "ecrdsa_iso", make_nonce("nonce_beta")),
        ("Certificate renewal request for node 42", "ecrdsa_rfc", make_nonce("nonce_gamma")),
        ("Heartbeat signal from sensor network", "ecrdsa_rfc", k_shared),  # CROSS-ALGO REUSE
        ("Key rotation event triggered", "ecdsa", make_nonce("nonce_delta")),
        ("Firmware update package checksum valid", "ecrdsa_iso", make_nonce("nonce_epsilon")),
        ("Authentication token refreshed", "ecrdsa_rfc", make_nonce("nonce_zeta")),
        ("Database migration completed successfully", "ecdsa", make_nonce("nonce_eta")),
    ]

    signatures = []
    ground_truth = []

    for i, (msg, algo, k) in enumerate(sigs_spec):
        W = scalar_mult(k, G, a, p)
        r_val = W[0] % n
        assert r_val != 0

        if algo == "ecdsa":
            s_val = ecdsa_sign(msg, k, d, r_val, n)
        elif algo == "ecrdsa_rfc":
            s_val = ecrdsa_rfc_sign(msg, k, d, r_val, n)
        elif algo == "ecrdsa_iso":
            s_val = ecrdsa_iso_sign(msg, k, d, r_val, n)
        else:
            raise ValueError(f"Unknown algo: {algo}")

        assert s_val != 0

        # Verify
        if algo == "ecdsa":
            assert ecdsa_verify(msg, r_val, s_val, Q, G, a, p, n), f"ECDSA verify failed for sig {i}"
        elif algo == "ecrdsa_rfc":
            assert ecrdsa_verify(msg, r_val, s_val, Q, G, a, p, n, False), f"ECRDSA-RFC verify failed for sig {i}"
        elif algo == "ecrdsa_iso":
            assert ecrdsa_verify(msg, r_val, s_val, Q, G, a, p, n, True), f"ECRDSA-ISO verify failed for sig {i}"

        signatures.append({
            "message": msg,
            "r": hex(r_val),
            "s": hex(s_val),
        })
        ground_truth.append(algo)

    # Verify cross-algorithm nonce reuse detection works
    assert signatures[0]["r"] == signatures[3]["r"], "Cross-algo nonce reuse: r values must match!"
    assert ground_truth[0] == "ecdsa" and ground_truth[3] == "ecrdsa_rfc"

    # Verify cross-algorithm recovery formula
    msg_ecdsa = sigs_spec[0][0]
    msg_ecrdsa = sigs_spec[3][0]
    s_ecdsa = int(signatures[0]["s"], 16)
    s_ecrdsa = int(signatures[3]["s"], 16)
    r_shared = int(signatures[0]["r"], 16)

    h_ecdsa = int.from_bytes(sha256_bytes(msg_ecdsa), 'big') % n
    h_ecrdsa_bytes = sha256_bytes(msg_ecrdsa)
    e_ecrdsa = int.from_bytes(h_ecrdsa_bytes[::-1], 'big') % n
    if e_ecrdsa == 0:
        e_ecrdsa = 1

    # k = (s_ecrdsa + h_ecdsa) / (s_ecdsa + e_ecrdsa) mod n
    k_recovered = ((s_ecrdsa + h_ecdsa) * modinv((s_ecdsa + e_ecrdsa) % n, n)) % n
    assert k_recovered == k_shared, f"Cross-algo recovery failed: got {hex(k_recovered)}, expected {hex(k_shared)}"

    # d = (s_ecdsa * k - h_ecdsa) / r mod n
    d_recovered = ((s_ecdsa * k_recovered - h_ecdsa) * modinv(r_shared, n)) % n
    assert d_recovered == d, "Private key recovery failed"

    captures = {
        "public_key": {"Qx": hex(Q[0]), "Qy": hex(Q[1])},
        "hash_algorithm": "sha256",
        "signatures": signatures,
    }

    # Write to stdout
    print(json.dumps(captures, indent=2))
    print(f"\n--- GROUND TRUTH ---", file=sys.stderr)
    print(f"Classifications: {ground_truth}", file=sys.stderr)
    print(f"Nonce reuse: sig 0 (ecdsa) and sig 3 (ecrdsa_rfc)", file=sys.stderr)
    print(f"Shared nonce k: {hex(k_shared)}", file=sys.stderr)
    print(f"Private key d: {hex(d)}", file=sys.stderr)
    print(f"Public key Q: ({hex(Q[0])}, {hex(Q[1])})", file=sys.stderr)


if __name__ == "__main__":
    main()
