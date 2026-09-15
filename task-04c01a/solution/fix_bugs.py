#!/usr/bin/env python3
"""
Fix the 5 bugs in /app/tcp_ao.py.

Bug 1: KDF label includes C null terminator (b"TCP-AO\\x00" -> b"TCP-AO")
Bug 2: KDF output length in little-endian instead of big-endian
Bug 3: KDF counter starts at 0 instead of 1
Bug 4: AES-CMAC key normalization uses pad/truncate instead of CMAC derivation
Bug 5: TCP checksum not zeroed before MAC computation

"""

with open("/app/tcp_ao.py") as f:
    code = f.read()

# Bug 1: Remove null terminator from label string
# The label "TCP-AO" should NOT include a C-style null byte (RFC 9235 Sec 8.3)
code = code.replace('b"TCP-AO\\x00"', 'b"TCP-AO"')

# Bug 2: Output length must be encoded in network byte order (big-endian)
# per RFC 5926 Section 3.1.1 (RFC 9235 Sec 8.2)
code = code.replace(
    'struct.pack("<H", output_length_bits)',
    'struct.pack("!H", output_length_bits)',
)

# Bug 3: Counter i must start at 1, not 0
# per RFC 5926 Section 3.1.1 (RFC 9235 Sec 8.2)
code = code.replace(
    "for i in range(blocks):",
    "for i in range(1, blocks + 1):",
)

# Bug 4: AES-CMAC key normalization must use AES-CMAC(0^128, MK)
# for non-16-byte master keys, per RFC 5926 Section 3.1.1.2
old_norm = "    k = master_key.ljust(16, b'\\x00')[:16]"
new_norm = (
    "    if len(master_key) == 16:\n"
    "        k = master_key\n"
    "    else:\n"
    "        k = aes_cmac(b'\\x00' * 16, master_key)"
)
code = code.replace(old_norm, new_norm)

# Bug 5: TCP checksum field (bytes 16-17 of TCP header) must be zeroed
# before MAC computation (RFC 9235 Sec 8.4)
code = code.replace(
    "    # tcp[16:18] = b'\\x00\\x00'",
    "    tcp[16:18] = b'\\x00\\x00'",
)

with open("/app/tcp_ao.py", "w") as f:
    f.write(code)

print("All 5 bugs fixed in /app/tcp_ao.py")
