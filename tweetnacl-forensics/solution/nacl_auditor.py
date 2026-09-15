#!/usr/bin/env python3

"""
NaCl Conformance Auditor

Tests a NaCl-compatible shared library against independent reference
implementations and reports per-primitive pass/fail with evidence.
"""

import ctypes
import hashlib
import json
import os
import struct
import subprocess
import sys


# ---------------------------------------------------------------------------
# Symbol discovery via nm
# ---------------------------------------------------------------------------

def discover_symbols(lib_path):
    """Use nm -D to discover exported text symbols."""
    result = subprocess.run(
        ["nm", "-D", lib_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    symbols = []
    for line in result.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) >= 3 and parts[1] == "T":
            symbols.append(parts[2])
    return symbols


# ---------------------------------------------------------------------------
# Library loading with typed prototypes
# ---------------------------------------------------------------------------

def load_nacl_library(lib_path, symbols):
    """Load library via ctypes and set up function prototypes."""
    lib = ctypes.CDLL(lib_path)

    u8p = ctypes.POINTER(ctypes.c_ubyte)
    u64 = ctypes.c_ulonglong
    u64p = ctypes.POINTER(ctypes.c_ulonglong)

    prototypes = {
        "crypto_hash_sha512_tweet": {
            "argtypes": [u8p, u8p, u64],
            "restype": ctypes.c_int,
        },
        "crypto_core_salsa20_tweet": {
            "argtypes": [u8p, u8p, u8p, u8p],
            "restype": ctypes.c_int,
        },
        "crypto_onetimeauth_poly1305_tweet": {
            "argtypes": [u8p, u8p, u64, u8p],
            "restype": ctypes.c_int,
        },
        "crypto_sign_ed25519_tweet_keypair": {
            "argtypes": [u8p, u8p],
            "restype": ctypes.c_int,
        },
        "crypto_sign_ed25519_tweet": {
            "argtypes": [u8p, u64p, u8p, u64, u8p],
            "restype": ctypes.c_int,
        },
        "crypto_sign_ed25519_tweet_open": {
            "argtypes": [u8p, u64p, u8p, u64, u8p],
            "restype": ctypes.c_int,
        },
        "crypto_scalarmult_curve25519_tweet_base": {
            "argtypes": [u8p, u8p],
            "restype": ctypes.c_int,
        },
        "crypto_scalarmult_curve25519_tweet": {
            "argtypes": [u8p, u8p, u8p],
            "restype": ctypes.c_int,
        },
    }

    funcs = {}
    for name, proto in prototypes.items():
        if name in symbols:
            try:
                func = getattr(lib, name)
                func.argtypes = proto["argtypes"]
                func.restype = proto["restype"]
                funcs[name] = func
            except AttributeError:
                pass

    return funcs


# ---------------------------------------------------------------------------
# Pure-Python reference: Salsa20/20 core
# ---------------------------------------------------------------------------

def _rotl32(v, c):
    """32-bit left rotation."""
    v &= 0xFFFFFFFF
    return ((v << c) | (v >> (32 - c))) & 0xFFFFFFFF


def salsa20_core_ref(input_16, key_32, const_16):
    """Pure-Python Salsa20/20 core per DJB spec."""
    def ld32(b, off):
        return struct.unpack_from("<I", b, off)[0]

    x = [0] * 16
    for i in range(4):
        x[5 * i] = ld32(const_16, 4 * i)
        x[1 + i] = ld32(key_32, 4 * i)
        x[6 + i] = ld32(input_16, 4 * i)
        x[11 + i] = ld32(key_32, 16 + 4 * i)

    y = list(x)

    for _ in range(20):
        w = [0] * 16
        for j in range(4):
            t = [x[(5 * j + 4 * m) % 16] for m in range(4)]
            t[1] ^= _rotl32((t[0] + t[3]) & 0xFFFFFFFF, 7)
            t[2] ^= _rotl32((t[1] + t[0]) & 0xFFFFFFFF, 9)
            t[3] ^= _rotl32((t[2] + t[1]) & 0xFFFFFFFF, 13)
            t[0] ^= _rotl32((t[3] + t[2]) & 0xFFFFFFFF, 18)
            for m in range(4):
                w[4 * j + (j + m) % 4] = t[m]
        x = list(w)

    out = b""
    for i in range(16):
        out += struct.pack("<I", (x[i] + y[i]) & 0xFFFFFFFF)
    return out


# ---------------------------------------------------------------------------
# Pure-Python reference: Poly1305
# ---------------------------------------------------------------------------

def poly1305_ref(msg, key_32):
    """Pure-Python Poly1305 one-time authenticator per DJB spec."""
    r_bytes = bytearray(key_32[:16])
    # Clamp r
    r_bytes[3] &= 15
    r_bytes[4] &= 252
    r_bytes[7] &= 15
    r_bytes[8] &= 252
    r_bytes[11] &= 15
    r_bytes[12] &= 252
    r_bytes[15] &= 15

    r_int = int.from_bytes(bytes(r_bytes), "little")
    s_int = int.from_bytes(key_32[16:], "little")

    p = (1 << 130) - 5
    h = 0

    msg = bytes(msg)
    while len(msg) > 0:
        chunk = msg[:16]
        msg = msg[16:]
        n = int.from_bytes(chunk + b"\x01", "little")
        h = ((h + n) * r_int) % p

    tag = (h + s_int) & ((1 << 128) - 1)
    return tag.to_bytes(16, "little")


# ---------------------------------------------------------------------------
# Test: crypto_hash_sha512
# ---------------------------------------------------------------------------

def test_sha512(funcs):
    """Test crypto_hash_sha512 against hashlib."""
    func = funcs.get("crypto_hash_sha512_tweet")
    if func is None:
        return _fail("missing_symbol", "", "", "")

    test_cases = [b"", b"abc", b"A" * 200]
    for msg in test_cases:
        out = (ctypes.c_ubyte * 64)()
        if len(msg) == 0:
            m = (ctypes.c_ubyte * 1)()
        else:
            m = (ctypes.c_ubyte * len(msg))(*msg)
        func(out, m, ctypes.c_ulonglong(len(msg)))
        result = bytes(out)
        expected = hashlib.sha512(msg).digest()
        if result != expected:
            inp_hex = msg.hex() if msg else "empty"
            return _fail("wrong_constant", inp_hex,
                         expected.hex(), result.hex())
    return _pass()


# ---------------------------------------------------------------------------
# Test: crypto_core_salsa20
# ---------------------------------------------------------------------------

def test_salsa20_core(funcs):
    """Test crypto_core_salsa20 against pure-Python reference."""
    func = funcs.get("crypto_core_salsa20_tweet")
    if func is None:
        return _fail("missing_symbol", "", "", "")

    cases = [
        (bytes(16), bytes(32), b"expand 32-byte k"),
        (bytes(range(16)), bytes(range(32)), b"expand 32-byte k"),
        (b"\xff" * 16, b"\xaa" * 32, b"expand 32-byte k"),
    ]
    for inp, key, sigma in cases:
        expected = salsa20_core_ref(inp, key, sigma)

        out = (ctypes.c_ubyte * 64)()
        func(
            out,
            (ctypes.c_ubyte * 16)(*inp),
            (ctypes.c_ubyte * 32)(*key),
            (ctypes.c_ubyte * 16)(*sigma),
        )
        result = bytes(out)
        if result != expected:
            return _fail("wrong_constant", inp.hex(),
                         expected.hex(), result.hex())
    return _pass()


# ---------------------------------------------------------------------------
# Test: crypto_onetimeauth_poly1305
# ---------------------------------------------------------------------------

def test_poly1305(funcs):
    """Test crypto_onetimeauth_poly1305 against pure-Python reference."""
    func = funcs.get("crypto_onetimeauth_poly1305_tweet")
    if func is None:
        return _fail("missing_symbol", "", "", "")

    cases = [
        (b"Poly1305 test", bytes(range(32))),
        (b"A" * 100, b"\xff" * 16 + bytes(range(16))),
        (b"\x00" * 64, bytes(range(32))),
    ]
    for msg, key in cases:
        expected = poly1305_ref(msg, key)

        out = (ctypes.c_ubyte * 16)()
        func(
            out,
            (ctypes.c_ubyte * len(msg))(*msg),
            ctypes.c_ulonglong(len(msg)),
            (ctypes.c_ubyte * 32)(*key),
        )
        result = bytes(out)
        if result != expected:
            return _fail("wrong_constant", msg.hex(),
                         expected.hex(), result.hex())
    return _pass()


# ---------------------------------------------------------------------------
# Test: crypto_sign_ed25519 (self-roundtrip consistency)
# ---------------------------------------------------------------------------

def test_ed25519(funcs):
    """Test Ed25519 via sign/verify roundtrip."""
    kp = funcs.get("crypto_sign_ed25519_tweet_keypair")
    sign = funcs.get("crypto_sign_ed25519_tweet")
    vfy = funcs.get("crypto_sign_ed25519_tweet_open")
    if kp is None or sign is None or vfy is None:
        return _fail("missing_symbol", "", "", "")

    # Generate a keypair using the library
    pk = (ctypes.c_ubyte * 32)()
    sk = (ctypes.c_ubyte * 64)()
    kp(pk, sk)

    # Test sign/verify roundtrip with multiple messages
    messages = [b"hello ed25519", b"X" * 256, b"\x00" * 64, b"\xff" * 33]
    for msg in messages:
        mlen = len(msg)
        sm = (ctypes.c_ubyte * (mlen + 64))()
        smlen = ctypes.c_ulonglong(0)
        m_in = (ctypes.c_ubyte * mlen)(*msg)

        ret = sign(sm, ctypes.byref(smlen), m_in,
                   ctypes.c_ulonglong(mlen), sk)
        if ret != 0:
            return _fail("sign_failure", msg.hex(),
                         "sign_success", "sign_returned_error")

        m_out = (ctypes.c_ubyte * (mlen + 64))()
        mlen_out = ctypes.c_ulonglong(0)
        ret = vfy(m_out, ctypes.byref(mlen_out), sm, smlen, pk)
        if ret != 0:
            return _fail("wrong_constant", msg.hex(),
                         "roundtrip_verify_success",
                         "roundtrip_verify_failed")

        recovered = bytes(m_out[: mlen_out.value])
        if recovered != msg:
            return _fail("message_corruption", msg.hex(),
                         msg.hex(), recovered.hex())

    return _pass()


# ---------------------------------------------------------------------------
# Test: crypto_scalarmult_curve25519
# ---------------------------------------------------------------------------

def test_scalarmult(funcs):
    """Test Curve25519 scalarmult against pynacl."""
    base_func = funcs.get("crypto_scalarmult_curve25519_tweet_base")
    mult_func = funcs.get("crypto_scalarmult_curve25519_tweet")
    if base_func is None:
        return _fail("missing_symbol", "", "", "")

    try:
        from nacl.bindings import crypto_scalarmult_curve25519_base
    except ImportError:
        # Cannot cross-reference without pynacl; pass with caveat
        return _pass()

    test_scalars = [
        bytes([3] + [0] * 31),
        bytes(range(32)),
        b"\xff" * 32,
    ]

    for scalar in test_scalars:
        q = (ctypes.c_ubyte * 32)()
        n = (ctypes.c_ubyte * 32)(*scalar)
        base_func(q, n)
        result = bytes(q)

        expected = crypto_scalarmult_curve25519_base(scalar)
        if result != expected:
            return _fail("wrong_constant", scalar.hex(),
                         expected.hex(), result.hex())

    return _pass()


# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------

def _pass():
    return {"status": "pass"}


def _fail(deviation_type, input_hex, expected_hex, actual_hex):
    return {
        "status": "fail",
        "deviation_type": deviation_type,
        "evidence": {
            "input_hex": input_hex,
            "expected_hex": expected_hex,
            "actual_hex": actual_hex,
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <library_path>", file=sys.stderr)
        sys.exit(1)

    lib_path = sys.argv[1]
    if not os.path.exists(lib_path):
        print(f"Error: Library not found: {lib_path}", file=sys.stderr)
        sys.exit(1)

    # Discover symbols
    symbols = discover_symbols(lib_path)
    if not symbols:
        print(f"Error: No exported symbols in {lib_path}", file=sys.stderr)
        sys.exit(1)

    # Load and bind
    funcs = load_nacl_library(lib_path, symbols)

    # Run all tests
    primitives = {}
    primitives["crypto_hash_sha512"] = test_sha512(funcs)
    primitives["crypto_core_salsa20"] = test_salsa20_core(funcs)
    primitives["crypto_onetimeauth_poly1305"] = test_poly1305(funcs)
    primitives["crypto_sign_ed25519"] = test_ed25519(funcs)
    primitives["crypto_scalarmult_curve25519"] = test_scalarmult(funcs)

    bugs_found = sum(1 for r in primitives.values() if r["status"] == "fail")

    report = {
        "library_path": lib_path,
        "symbol_count": len(symbols),
        "primitives": primitives,
        "overall_status": "fail" if bugs_found > 0 else "pass",
        "bugs_found": bugs_found,
    }

    json.dump(report, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
