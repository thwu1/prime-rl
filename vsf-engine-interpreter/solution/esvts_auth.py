
"""
ESVTS Authentication Module

Implements TOTP (RFC 6238) and JWT (HS256) for the mock ESVTS server.
"""

import hmac
import hashlib
import struct
import json
import base64
import time as time_mod


# ============================================================
# TOTP (RFC 6238) — HMAC-SHA1, configurable step/digits
# ============================================================


def generate_totp(seed: bytes, timestamp: int = None, step: int = 30, digits: int = 8) -> str:
    """Generate a TOTP code per RFC 6238."""
    if timestamp is None:
        timestamp = int(time_mod.time())

    # Time counter
    T = timestamp // step
    msg = struct.pack(">Q", T)

    # HMAC-SHA1
    h = hmac.new(seed, msg, hashlib.sha1).digest()

    # Dynamic truncation
    offset = h[-1] & 0x0F
    code_int = (
        ((h[offset] & 0x7F) << 24)
        | (h[offset + 1] << 16)
        | (h[offset + 2] << 8)
        | h[offset + 3]
    )

    code_int = code_int % (10 ** digits)
    return str(code_int).zfill(digits)


def verify_totp(
    seed: bytes,
    code: str,
    timestamp: int = None,
    step: int = 30,
    digits: int = 8,
    window: int = 1,
) -> bool:
    """Verify a TOTP code within ±window time steps."""
    if timestamp is None:
        timestamp = int(time_mod.time())

    T_current = timestamp // step
    for offset in range(-window, window + 1):
        t = (T_current + offset) * step
        if generate_totp(seed, timestamp=t, step=step, digits=digits) == code:
            return True
    return False


# ============================================================
# JWT (HS256) — JSON Web Token with HMAC-SHA256
# ============================================================


def _base64url_encode(data: bytes) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _base64url_decode(s: str) -> bytes:
    """Base64url decode with padding restoration."""
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_jwt(claims: dict, secret: str, expires_in: int = 1800) -> str:
    """Create a signed JWT with HS256."""
    header = {"alg": "HS256", "typ": "JWT"}

    payload = dict(claims)
    now = int(time_mod.time())
    if "iat" not in payload:
        payload["iat"] = now
    if "exp" not in payload:
        payload["exp"] = now + expires_in

    header_b64 = _base64url_encode(
        json.dumps(header, separators=(",", ":")).encode()
    )
    payload_b64 = _base64url_encode(
        json.dumps(payload, separators=(",", ":")).encode()
    )

    signing_input = f"{header_b64}.{payload_b64}"
    sig = hmac.new(
        secret.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256
    ).digest()
    sig_b64 = _base64url_encode(sig)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def verify_jwt(token: str, secret: str):
    """Verify and decode a JWT. Returns payload dict or None."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        header_b64, payload_b64, sig_b64 = parts

        # Recompute signature
        signing_input = f"{header_b64}.{payload_b64}"
        expected_sig = hmac.new(
            secret.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256
        ).digest()
        actual_sig = _base64url_decode(sig_b64)

        if not hmac.compare_digest(expected_sig, actual_sig):
            return None

        # Decode payload
        payload = json.loads(_base64url_decode(payload_b64))

        # Check expiry
        if "exp" in payload and payload["exp"] < int(time_mod.time()):
            return None

        return payload
    except Exception:
        return None
