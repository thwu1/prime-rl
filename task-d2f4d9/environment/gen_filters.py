#!/usr/bin/env python3
"""Generate binary BPF filter files for the SECCOMP audit task.
Each instruction is 8 bytes: 2-byte LE code, 1-byte jt, 1-byte jf, 4-byte LE k.
This matches the Linux kernel's struct sock_filter wire format.
"""
import struct

FILTERS = {
    "stdio_mmap": [
        (0x20, 0, 0, 0),         # LD nr
        (0x15, 7, 0, 0),         # JEQ read -> ALLOW
        (0x15, 6, 0, 1),         # JEQ write -> ALLOW
        (0x15, 5, 0, 60),        # JEQ exit -> ALLOW
        (0x15, 4, 0, 231),       # JEQ exit_group -> ALLOW
        (0x15, 3, 0, 12),        # JEQ brk -> ALLOW
        (0x15, 0, 3, 9),         # JEQ mmap -> check prot; else KILL
        (0x20, 0, 0, 24),        # LD offset 24 [BUG: loads args[1]=length, should be offset 32 for args[2]=prot]
        (0x45, 1, 0, 4),         # JSET PROT_EXEC -> KILL
        (0x06, 0, 0, 0x7FFF0000),# RET ALLOW
        (0x06, 0, 0, 0),         # RET KILL
    ],
    "network_socket": [
        (0x20, 0, 0, 0),         # LD nr
        (0x15, 13, 0, 0),        # JEQ read -> ALLOW
        (0x15, 12, 0, 1),        # JEQ write -> ALLOW
        (0x15, 11, 0, 3),        # JEQ close -> ALLOW
        (0x15, 10, 0, 42),       # JEQ connect -> ALLOW
        (0x15, 9, 0, 44),        # JEQ sendto -> ALLOW
        (0x15, 8, 0, 45),        # JEQ recvfrom -> ALLOW
        (0x15, 0, 8, 41),        # JEQ socket -> check domain; else KILL
        (0x20, 0, 0, 16),        # LD args[0] (domain)
        (0x15, 1, 0, 2),         # JEQ AF_INET -> check type
        (0x15, 1, 5, 10),        # JEQ AF_INET6 [BUG: jt=1 skips type load, should be jt=0]
        (0x20, 0, 0, 24),        # LD args[1] (type)
        (0x54, 0, 0, 0xFFF7F7FF),# AND ~(SOCK_CLOEXEC|SOCK_NONBLOCK)
        (0x15, 1, 0, 1),         # JEQ SOCK_STREAM -> ALLOW
        (0x15, 0, 1, 2),         # JEQ SOCK_DGRAM -> ALLOW; else KILL
        (0x06, 0, 0, 0x7FFF0000),# RET ALLOW
        (0x06, 0, 0, 0),         # RET KILL
    ],
    "fs_readonly": [
        (0x20, 0, 0, 0),         # LD nr
        (0x15, 9, 0, 0),         # JEQ read -> ALLOW
        (0x15, 8, 0, 3),         # JEQ close -> ALLOW
        (0x15, 7, 0, 5),         # JEQ fstat -> ALLOW
        (0x15, 6, 0, 8),         # JEQ lseek -> ALLOW
        (0x15, 5, 0, 60),        # JEQ exit -> ALLOW
        (0x15, 4, 0, 231),       # JEQ exit_group -> ALLOW
        (0x15, 0, 4, 2),         # JEQ open -> check flags; else KILL
        (0x20, 0, 0, 28),        # LD offset 28 [BUG: loads high 32 bits of args[1], should be offset 24 for low bits]
        (0x54, 0, 0, 3),         # AND O_ACCMODE
        (0x15, 0, 1, 0),         # JEQ O_RDONLY -> ALLOW; else KILL
        (0x06, 0, 0, 0x7FFF0000),# RET ALLOW
        (0x06, 0, 0, 0),         # RET KILL
    ],
}

for name, insns in FILTERS.items():
    data = bytearray()
    for code, jt, jf, k in insns:
        data += struct.pack('<HBBI', code, jt, jf, k)
    with open(f'/app/{name}.bpf', 'wb') as f:
        f.write(data)
    print(f"Generated /app/{name}.bpf ({len(insns)} instructions, {len(data)} bytes)")
