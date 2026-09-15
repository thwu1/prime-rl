#!/usr/bin/env python3
"""
Fix all bugs in /app/tcp_ao.py.

The implementation has 6 bugs based on common TCP-AO implementation errors
documented in RFC 9235 Section 8:

1. KDF counter starts at 0 instead of 1 (Section 8.2)
2. Label "TCP-AO" includes a trailing null byte (Section 8.3)
3. Output_Length encoded in little-endian instead of network byte order (Section 8.2)
4. AES-128-CMAC KDF key normalization uses zero-padding instead of
   AES-CMAC(0^128, MK) per RFC 4615/5926 (Section 8.2)
5. TCP checksum field not zeroed before MAC computation (Section 8.4)
6. When TCP options are excluded, the TCP-AO option must still be
   included in the MAC input (Section 8.4 / RFC 5925 Section 5.1)
"""

import re

with open('/app/tcp_ao.py', 'r') as f:
    code = f.read()

# ---- Bug 1: KDF counter must start at i=1, not i=0 ----
# RFC 5926 Section 3.1.1: "i always starts = 1"
code = code.replace(
    'for i in range(num_blocks):',
    'for i in range(1, num_blocks + 1):'
)

# ---- Bug 2: Label must NOT include null terminator ----
# RFC 9235 Section 8.3: 'The label "TCP-AO" includes the last zero byte (it should not).'
code = code.replace(
    'b"TCP-AO\\x00"',
    'b"TCP-AO"'
)

# ---- Bug 3: Output_Length must be in network byte order (big-endian) ----
# RFC 5926 Section 3.1.1: "Output_Length ... contained in two bytes in network byte order"
code = code.replace(
    "struct.pack('<H', output_length_bits)",
    "struct.pack('!H', output_length_bits)"
)

# ---- Bug 4: AES-128-CMAC key normalization per RFC 4615/5926 ----
# When master key length != 16, must use AES-CMAC(0^128, MK) to derive K
code = code.replace(
    '# Normalize variable-length key to 16 bytes\n'
    "        derived_key = (master_key + b'\\x00' * 16)[:16]",
    '# Normalize variable-length key using AES-CMAC with zero key (RFC 4615/5926)\n'
    "        derived_key = aes_128_cmac(b'\\x00' * 16, master_key)"
)

# ---- Bug 5: TCP checksum must be zeroed before MAC computation ----
# RFC 9235 Section 8.4: "TCP checksum ... is not zeroed properly before calculation"
code = code.replace(
    '    # Construct MAC input message\n'
    "    sne_bytes = struct.pack('!I', sne)",
    '    # Zero the TCP checksum field (bytes 16-17 of TCP header)\n'
    "    tcp[16:18] = b'\\x00\\x00'\n"
    '\n'
    '    # Construct MAC input message\n'
    "    sne_bytes = struct.pack('!I', sne)"
)

# ---- Bug 6: Omits-options must still include TCP-AO option ----
# RFC 5925 Section 5.1: "When TCP options are not included, all TCP
# options except for TCP-AO are omitted from MAC processing."
code = code.replace(
    '        tcp_header_bytes = bytes(tcp[:20])',
    '        # Include fixed header + TCP-AO option (with zeroed MAC)\n'
    '        tcp_header_bytes = bytes(tcp[:20]) + bytes(tcp[ao_offset:ao_offset + ao_len])'
)

with open('/app/tcp_ao.py', 'w') as f:
    f.write(code)

print("Fixed all 6 bugs in /app/tcp_ao.py:")
print("  1. KDF counter now starts at i=1")
print("  2. Label 'TCP-AO' no longer includes null byte")
print("  3. Output_Length now uses network byte order")
print("  4. AES-CMAC KDF key normalization uses AES-CMAC(0^128, MK)")
print("  5. TCP checksum zeroed before MAC computation")
print("  6. Omits-options MAC input now includes TCP-AO option")
