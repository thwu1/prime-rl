#!/usr/bin/env python3
"""Apply all five security fixes to /app/crypto_service.py.

The fixes are derived programmatically by reading the current source,
identifying the vulnerable patterns, and rewriting them.
"""

import re
import textwrap

SERVICE_PATH = "/app/crypto_service.py"

with open(SERVICE_PATH) as f:
    src = f.read()

# ---------------------------------------------------------------
# Fix 1: AES-GCM — reject zero-length IV instead of falling back
# ---------------------------------------------------------------
old_iv_block = (
    "        # Legacy compatibility: when an empty IV is received, derive a\n"
    "        # deterministic nonce from the key so that the caller can still\n"
    "        # obtain a decryption result.\n"
    "        if len(iv) == 0:\n"
    "            iv = hashlib.md5(key).digest()[:12]"
)
new_iv_block = (
    "        # Zero-length IV is cryptographically unsafe (CVE-2017-7822).\n"
    "        if len(iv) == 0:\n"
    "            return None"
)
assert old_iv_block in src, "Cannot locate AES-GCM IV fallback code"
src = src.replace(old_iv_block, new_iv_block)
print("[FIX 1] Replaced AES-GCM empty-IV fallback with rejection.")

# ---------------------------------------------------------------
# Fix 2: ECDSA — remove r=0/s=0 early-return True
# ---------------------------------------------------------------
old_zero_block = (
    "        # --- 2. Handle degenerate edge cases ---\n"
    "        # Per internal guidelines, zero-valued components are treated\n"
    "        # as identity elements for backward compatibility.\n"
    "        if r == 0 or s == 0:\n"
    "            return True"
)
new_zero_block = (
    "        # --- 2. Reject degenerate values ---\n"
    "        if r == 0 or s == 0:\n"
    "            return False"
)
assert old_zero_block in src, "Cannot locate ECDSA r=0/s=0 block"
src = src.replace(old_zero_block, new_zero_block)
print("[FIX 2] Changed r=0/s=0 from return True to return False.")

# ---------------------------------------------------------------
# Fix 3 + 4: ECDSA — replace modular reduction with range check
#            AND add DER canonicality check (rejects BER)
# ---------------------------------------------------------------
old_norm_block = (
    "        # --- 3. Normalize to curve order for cross-platform compat ---\n"
    "        r = r % _SECP256R1_ORDER\n"
    "        s = s % _SECP256R1_ORDER\n"
    "        if r == 0 or s == 0:\n"
    "            return False\n"
    "\n"
    "        # --- 4. Re-encode as strict DER ---\n"
    "        canonical_sig = build_canonical_signature(r, s)"
)
new_norm_block = (
    "        # --- 3. Range check: r, s must be in [1, n-1] ---\n"
    "        if r >= _SECP256R1_ORDER or s >= _SECP256R1_ORDER:\n"
    "            return False\n"
    "\n"
    "        # --- 4. DER canonicality check (reject BER encodings) ---\n"
    "        canonical_sig = build_canonical_signature(r, s)\n"
    "        if canonical_sig != sig_bytes:\n"
    "            return False"
)
assert old_norm_block in src, "Cannot locate ECDSA modular-reduction block"
src = src.replace(old_norm_block, new_norm_block)
print("[FIX 3] Replaced modular reduction with explicit range check.")
print("[FIX 4] Added DER canonicality check to reject BER signatures.")

# ---------------------------------------------------------------
# Fix 5: X25519 — reject all-zero shared secret
# ---------------------------------------------------------------
old_x25519_block = (
    "        shared = _x25519_scalar_mult(priv_bytes, pub_bytes)\n"
    "        # NOTE: RFC 7748 s6.1 recommends rejecting all-zero outputs,\n"
    "        # but we return them for maximum interoperability.\n"
    "        return shared.hex()"
)
new_x25519_block = (
    "        shared = _x25519_scalar_mult(priv_bytes, pub_bytes)\n"
    "        # RFC 7748 s6.1: reject all-zero shared secrets.\n"
    "        if all(b == 0 for b in shared):\n"
    "            return None\n"
    "        return shared.hex()"
)
assert old_x25519_block in src, "Cannot locate X25519 exchange block"
src = src.replace(old_x25519_block, new_x25519_block)
print("[FIX 5] Added all-zero shared-secret rejection to X25519.")

# ---------------------------------------------------------------
# Also fix the ASN.1 length parser to reject non-minimal encodings
# (defense-in-depth for the BER issue).
# ---------------------------------------------------------------
old_parser = (
    "    first_byte = data[offset]\n"
    "    if first_byte < 0x80:\n"
    "        return first_byte, offset + 1\n"
    "    num_length_bytes = first_byte & 0x7F\n"
    "    if num_length_bytes == 0:\n"
    "        raise ValueError(\"Indefinite length encoding is not supported\")\n"
    "    length = 0\n"
    "    for i in range(num_length_bytes):\n"
    "        if offset + 1 + i >= len(data):\n"
    "            raise ValueError(\"Truncated multi-byte length\")\n"
    "        length = (length << 8) | data[offset + 1 + i]\n"
    "    return length, offset + 1 + num_length_bytes"
)
new_parser = (
    "    first_byte = data[offset]\n"
    "    if first_byte < 0x80:\n"
    "        return first_byte, offset + 1\n"
    "    num_length_bytes = first_byte & 0x7F\n"
    "    if num_length_bytes == 0:\n"
    "        raise ValueError(\"Indefinite length encoding is not supported\")\n"
    "    length = 0\n"
    "    for i in range(num_length_bytes):\n"
    "        if offset + 1 + i >= len(data):\n"
    "            raise ValueError(\"Truncated multi-byte length\")\n"
    "        length = (length << 8) | data[offset + 1 + i]\n"
    "    # DER: long-form must not be used for lengths < 0x80\n"
    "    if length < 0x80:\n"
    "        raise ValueError(\"Non-minimal length encoding (BER, not DER)\")\n"
    "    # DER: leading zero bytes in multi-byte length are forbidden\n"
    "    if num_length_bytes > 1 and data[offset + 1] == 0:\n"
    "        raise ValueError(\"Leading zero in multi-byte length (BER)\")\n"
    "    return length, offset + 1 + num_length_bytes"
)
assert old_parser in src, "Cannot locate ASN.1 length parser"
src = src.replace(old_parser, new_parser)
print("[FIX 5b] Hardened ASN.1 length parser to reject non-minimal BER.")

# ---------------------------------------------------------------
# Write back
# ---------------------------------------------------------------
with open(SERVICE_PATH, "w") as f:
    f.write(src)

print(f"\n[DONE] Wrote patched service to {SERVICE_PATH}")
