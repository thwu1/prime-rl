#!/usr/bin/env python3
"""Generate program.bin - bytecode for the custom VM cipher challenge."""

import sys

# ---- Configuration ----
KEY = bytes([0xDE, 0xAD, 0xBE, 0xEF])
FLAG = b"OOO{r3v3rs3_th3_vm_br34k_c1ph3r}"
assert len(FLAG) == 32

# ---- Key expansion ----
def expand_key(key):
    d = [0] * 32
    d[0] = (key[0] + 0x37) & 0xFF
    d[1] = key[1] ^ 0x5A
    d[2] = (key[2] + 0x13) & 0xFF
    d[3] = key[3] ^ 0x7F
    for i in range(4, 32):
        d[i] = ((d[i-4] + d[i-3] + d[i-1]) ^ d[i-2]) & 0xFF
    return d

keystream = expand_key(KEY)
ciphertext = [f ^ k for f, k in zip(FLAG, keystream)]
checksum = sum(FLAG) & 0xFF

# ---- Bytecode emitter ----
code = bytearray()

def emit(*bs):
    for b in bs:
        code.append(b & 0xFF)

# ==== Section 1: Read 4-byte key into mem[0..3] ====
for i in range(4):
    emit(0x15)        # READ
    emit(0x01, i)     # PUSH addr
    emit(0x0F)        # STORE

# ==== Section 2: Initial key derivation (4 blocks) ====
# d[0] = (k[0] + 0x37) & 0xFF
emit(0x01, 0); emit(0x0E)       # PUSH 0; LOAD
emit(0x01, 0x37); emit(0x05)    # PUSH 0x37; ADD
emit(0x01, 4); emit(0x0F)       # PUSH 4; STORE

# d[1] = k[1] ^ 0x5A
emit(0x01, 1); emit(0x0E)
emit(0x01, 0x5A); emit(0x08)    # XOR
emit(0x01, 5); emit(0x0F)

# d[2] = (k[2] + 0x13) & 0xFF
emit(0x01, 2); emit(0x0E)
emit(0x01, 0x13); emit(0x05)    # ADD
emit(0x01, 6); emit(0x0F)

# d[3] = k[3] ^ 0x7F
emit(0x01, 3); emit(0x0E)
emit(0x01, 0x7F); emit(0x08)    # XOR
emit(0x01, 7); emit(0x0F)

# ==== Section 3: Extended key derivation, i=4..31 ====
# d[i] = (d[i-4] + d[i-3] + d[i-1]) ^ d[i-2]
# Memory layout: d[j] stored at mem[4+j], so d[i-k] is at mem[4+i-k] = mem[i+(4-k)]
for i in range(4, 32):
    emit(0x01, i);     emit(0x0E)   # LOAD d[i-4] from mem[i]
    emit(0x01, i + 1); emit(0x0E)   # LOAD d[i-3] from mem[i+1]
    emit(0x05)                       # ADD
    emit(0x01, i + 3); emit(0x0E)   # LOAD d[i-1] from mem[i+3]
    emit(0x05)                       # ADD
    emit(0x01, i + 2); emit(0x0E)   # LOAD d[i-2] from mem[i+2]
    emit(0x08)                       # XOR
    emit(0x01, 4 + i); emit(0x0F)   # STORE d[i] at mem[4+i]

# ==== Section 4: Load hardcoded ciphertext into mem[36..67] ====
for i in range(32):
    emit(0x01, ciphertext[i])
    emit(0x01, 36 + i)
    emit(0x0F)

# ==== Section 5: Decrypt - plaintext[i] = ct[i] ^ derived[i] ====
for i in range(32):
    emit(0x01, 36 + i); emit(0x0E)  # LOAD ciphertext[i]
    emit(0x01, 4 + i);  emit(0x0E)  # LOAD derived[i]
    emit(0x08)                       # XOR
    emit(0x01, 68 + i); emit(0x0F)  # STORE plaintext[i]

# ==== Section 6: Compute checksum of plaintext ====
emit(0x01, 0)  # accumulator = 0
for i in range(32):
    emit(0x01, 68 + i); emit(0x0E)  # LOAD plaintext[i]
    emit(0x05)                       # ADD
emit(0x01, 100); emit(0x0F)         # STORE at mem[100]

# ==== Section 7: Compare checksum, branch to DENIED if mismatch ====
emit(0x01, 100); emit(0x0E)         # LOAD checksum
emit(0x01, checksum)                 # PUSH expected
emit(0x1A)                           # CMP_EQ

# Calculate DENIED address: current pos + 3 (jz) + success section
success_size = 32 * 4 + 1  # 32 x (PUSH+LOAD+WRITE) + HALT
denied_addr = len(code) + 3 + success_size

emit(0x11)                           # JZ
emit((denied_addr >> 8) & 0xFF)
emit(denied_addr & 0xFF)

# ==== Section 8: Success - output decrypted flag ====
for i in range(32):
    emit(0x01, 68 + i); emit(0x0E)  # LOAD plaintext[i]
    emit(0x16)                       # WRITE
emit(0x17)                           # HALT

assert len(code) == denied_addr, f"Address mismatch: {len(code)} != {denied_addr}"

# ==== Section 9: Output "DENIED\n" and halt ====
for c in b"DENIED\n":
    emit(0x01, c)
    emit(0x16)
emit(0x17)

# ---- Write output ----
with open('/app/program.bin', 'wb') as f:
    f.write(bytes(code))

print(f"Generated {len(code)} bytes of bytecode", file=sys.stderr)
