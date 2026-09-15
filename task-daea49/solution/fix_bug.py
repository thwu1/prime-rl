"""Fix the two bugs in the XAES-256-GCM implementation.


Bug 1 - CMAC K1 derivation (in _derive_k1):
    The R_b polynomial for GF(2^128) is 0x00...0087 (the 0x87 byte is at
    the LAST byte position, index 15). The buggy code XORs 0x87 at index 0
    (the FIRST byte), which is an endianness error.
    Fix: shifted[0] ^= 0x87  -->  shifted[15] ^= 0x87

Bug 2 - Counter encoding (in _derive_subkey_and_nonce):
    The KDF counter is a 16-bit unsigned integer in big-endian (network)
    byte order. counter(1) = 0x00 0x01, counter(2) = 0x00 0x02. The buggy
    code encodes them as 0x01 0x00 and 0x02 0x00 (little-endian).
    Fix: bytes([0x01, 0x00, ...])  -->  bytes([0x00, 0x01, ...])
         bytes([0x02, 0x00, ...])  -->  bytes([0x00, 0x02, ...])
"""

with open("/app/xaes256gcm.py", "r") as f:
    code = f.read()

# Fix 1: CMAC polynomial XOR position (index 0 -> index 15)
code = code.replace("shifted[0] ^= 0x87", "shifted[15] ^= 0x87")

# Fix 2: Counter byte order (little-endian -> big-endian)
code = code.replace(
    "bytes([0x01, 0x00, 0x58, 0x00])",
    "bytes([0x00, 0x01, 0x58, 0x00])",
)
code = code.replace(
    "bytes([0x02, 0x00, 0x58, 0x00])",
    "bytes([0x00, 0x02, 0x58, 0x00])",
)

with open("/app/xaes256gcm.py", "w") as f:
    f.write(code)

# Verify the fix
import sys
sys.path.insert(0, "/app")
import importlib
import xaes256gcm
importlib.reload(xaes256gcm)

from xaes256gcm import XAES256GCM

# Quick smoke test with known vectors
tv1_key = bytes.fromhex(
    "df3f619804a92fdb4057192dc43dd748ea778adc52bc498ce80524c014b81119"
)
tv1_ct = XAES256GCM(tv1_key).encrypt(b"\xaa" * 24, b"test vector one", b"aad1")
assert tv1_ct.hex() == "bf69fc60fa8d13d40d0fa9865bca7d222dfcac5e8a147a54300fcdbf0bcbe8"

tv2_key = bytes.fromhex(
    "b40711a88c7039756fb8a73827eabe2c0fe5a0346ca7e0a104adc0fc764f528d"
)
tv2_ct = XAES256GCM(tv2_key).encrypt(b"\xbb" * 24, b"test vector two", b"aad2")
assert tv2_ct.hex() == "de34f0984522b2433ac92666e39414156ce57090de85652ec13b28dd90a858"

print("Both bugs fixed and verified successfully.")
