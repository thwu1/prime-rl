"""Fix the two bugs in the Python XAES-256-GCM implementation.


Bug 1 - MSB check on wrong byte (in _derive_k1):
    The MSB_1(L) check reads L[15] (the last byte) instead of L[0] (the first
    byte). MSB_1 is the most significant bit of the 128-bit big-endian value,
    which is bit 7 of the FIRST byte (index 0). The buggy code checks the
    last byte, causing the R_b XOR to be applied on the wrong condition.
    Fix: (L[15] >> 7) -> (L[0] >> 7)

Bug 2 - Counter byte order (in _derive_subkey_and_nonce):
    The KDF counter is encoded in little-endian (0x01 0x00 for counter 1)
    instead of big-endian/network byte order (0x00 0x01). The spec says
    counter(i) is a 16-bit unsigned integer in network byte order.
    Fix: bytes([0x01, 0x00, ...]) -> bytes([0x00, 0x01, ...])
         bytes([0x02, 0x00, ...]) -> bytes([0x00, 0x02, ...])
"""

with open("/app/py_impl/xaes256gcm.py", "r") as f:
    code = f.read()

# Fix 1: MSB check - use first byte (L[0]) not last byte (L[15])
code = code.replace("(L[15] >> 7) & 1", "(L[0] >> 7) & 1")

# Fix 2: Counter byte order - big-endian (network order)
code = code.replace(
    "bytes([0x01, 0x00, 0x58, 0x00])",
    "bytes([0x00, 0x01, 0x58, 0x00])",
)
code = code.replace(
    "bytes([0x02, 0x00, 0x58, 0x00])",
    "bytes([0x00, 0x02, 0x58, 0x00])",
)

with open("/app/py_impl/xaes256gcm.py", "w") as f:
    f.write(code)

print("Python implementation fixed (2 bugs).")
