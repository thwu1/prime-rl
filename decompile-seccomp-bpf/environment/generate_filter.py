#!/usr/bin/env python3
"""
Generate a 60-instruction seccomp-BPF classic BPF filter binary.

Filter policy:
  - Architecture: x86_64 only (KILL_PROCESS on mismatch)
  - Default: ERRNO(1) [EPERM]
  - 20 unconditionally allowed syscalls
  - socket: conditional on arg0 (AF_UNIX=1, AF_INET=2, AF_INET6=10, AF_NETLINK=16)
  - clone: conditional MASKED_EQ on arg0 (block CLONE_NEWUSER=0x10000000)
  - ioctl: conditional on arg1 (TCGETS=0x5401, TIOCGWINSZ=0x5413, FIONREAD=0x541B)
  - prctl: conditional on arg0 (PR_SET_NO_NEW_PRIVS=38, PR_SET_NAME=15, PR_GET_NAME=16)
  - ptrace: LOG
  - mount: ERRNO(13) [EACCES]
  - process_vm_readv, process_vm_writev: KILL_PROCESS

Instruction layout (60 total):
  pc  0-2:   arch check
  pc  3:     load syscall nr
  pc  4-23:  20 unconditional allow JEQs → pc 33 (RET ALLOW)
  pc 24-31:  8 conditional/special JEQs → handlers
  pc 32:     RET ERRNO(1) [default]
  pc 33:     RET ALLOW [shared target]
  pc 34-40:  socket handler (LD arg0 + 4 JEQ + RET ERRNO + RET ALLOW)
  pc 41-44:  clone handler (LD arg0 + JSET + RET ERRNO + RET ALLOW)
  pc 45-50:  ioctl handler (LD arg1 + 3 JEQ + RET ERRNO + RET ALLOW)
  pc 51-56:  prctl handler (LD arg0 + 3 JEQ + RET ERRNO + RET ALLOW)
  pc 57:     ptrace → RET LOG
  pc 58:     mount → RET ERRNO(13)
  pc 59:     process_vm_readv/writev → RET KILL_PROCESS
"""
import struct
import sys


def _s(c, k):
    """Emit a statement instruction (no jumps)."""
    return struct.pack('<HBBI', c, 0, 0, k)


def _j(c, k, t, f):
    """Emit a jump instruction: code, k-value, jt-offset, jf-offset."""
    return struct.pack('<HBBI', c, t, f, k)


def generate(out):
    p = []

    # ── Block 1: Architecture check (pc 0-2) ──
    p.append(_s(0x20, 4))                     # 0: LD [4] (arch)
    p.append(_j(0x15, 0xC000003E, 1, 0))      # 1: JEQ AUDIT_ARCH_X86_64 → 3
    p.append(_s(0x06, 0x80000000))             # 2: RET KILL_PROCESS

    # ── Block 2: Load syscall number (pc 3) ──
    p.append(_s(0x20, 0))                      # 3: LD [0] (syscall nr)

    # ── Block 3: Unconditional allow JEQ chain (pc 4-23) ──
    # All jump to pc 33 (RET ALLOW). jt = 33 - (pc+1).
    # Syscalls in ascending order of number:
    unconditional = [
        (0,   28),   # read       jt=33-5=28
        (1,   27),   # write      jt=33-6=27
        (3,   26),   # close      jt=33-7=26
        (5,   25),   # fstat      jt=33-8=25
        (8,   24),   # lseek      jt=33-9=24
        (9,   23),   # mmap       jt=33-10=23
        (10,  22),   # mprotect   jt=33-11=22
        (11,  21),   # munmap     jt=33-12=21
        (12,  20),   # brk        jt=33-13=20
        (13,  19),   # rt_sigaction jt=33-14=19
        (14,  18),   # rt_sigprocmask jt=33-15=18
        (21,  17),   # access     jt=33-16=17
        (22,  16),   # pipe       jt=33-17=16
        (35,  15),   # nanosleep  jt=33-18=15
        (39,  14),   # getpid     jt=33-19=14
        (60,  13),   # exit       jt=33-20=13
        (79,  12),   # getcwd     jt=33-21=12
        (102, 11),   # getuid     jt=33-22=11
        (186, 10),   # gettid     jt=33-23=10
        (231,  9),   # exit_group jt=33-24=9
    ]
    for nr, jt in unconditional:
        p.append(_j(0x15, nr, jt, 0))         # pc 4-23

    # ── Block 4: Conditional/special JEQ chain (pc 24-31) ──
    p.append(_j(0x15, 41,  9, 0))              # 24: socket(41) → 34
    p.append(_j(0x15, 56, 15, 0))              # 25: clone(56)  → 41
    p.append(_j(0x15, 16, 18, 0))              # 26: ioctl(16)  → 45
    p.append(_j(0x15, 157, 23, 0))             # 27: prctl(157) → 51
    p.append(_j(0x15, 101, 28, 0))             # 28: ptrace(101) → 57
    p.append(_j(0x15, 165, 28, 0))             # 29: mount(165) → 58
    p.append(_j(0x15, 310, 28, 0))             # 30: process_vm_readv(310) → 59
    p.append(_j(0x15, 311, 27, 0))             # 31: process_vm_writev(311) → 59

    # ── Block 5: Default action (pc 32) ──
    p.append(_s(0x06, 0x00050001))             # 32: RET ERRNO(1) [EPERM]

    # ── Block 6: Shared unconditional ALLOW (pc 33) ──
    p.append(_s(0x06, 0x7FFF0000))             # 33: RET ALLOW

    # ── Block 7: Socket handler (pc 34-40) ──
    p.append(_s(0x20, 16))                     # 34: LD [16] (arg0)
    p.append(_j(0x15, 1,  4, 0))               # 35: JEQ AF_UNIX(1) → 40
    p.append(_j(0x15, 2,  3, 0))               # 36: JEQ AF_INET(2) → 40
    p.append(_j(0x15, 10, 2, 0))               # 37: JEQ AF_INET6(10) → 40
    p.append(_j(0x15, 16, 1, 0))               # 38: JEQ AF_NETLINK(16) → 40
    p.append(_s(0x06, 0x00050001))             # 39: RET ERRNO(1)
    p.append(_s(0x06, 0x7FFF0000))             # 40: RET ALLOW

    # ── Block 8: Clone handler (pc 41-44) ──
    p.append(_s(0x20, 16))                     # 41: LD [16] (arg0)
    p.append(_j(0x45, 0x10000000, 0, 1))       # 42: JSET CLONE_NEWUSER → 43, else → 44
    p.append(_s(0x06, 0x00050001))             # 43: RET ERRNO(1)
    p.append(_s(0x06, 0x7FFF0000))             # 44: RET ALLOW

    # ── Block 9: Ioctl handler (pc 45-50) ──
    p.append(_s(0x20, 24))                     # 45: LD [24] (arg1)
    p.append(_j(0x15, 0x5401, 3, 0))           # 46: JEQ TCGETS → 50
    p.append(_j(0x15, 0x5413, 2, 0))           # 47: JEQ TIOCGWINSZ → 50
    p.append(_j(0x15, 0x541B, 1, 0))           # 48: JEQ FIONREAD → 50
    p.append(_s(0x06, 0x00050001))             # 49: RET ERRNO(1)
    p.append(_s(0x06, 0x7FFF0000))             # 50: RET ALLOW

    # ── Block 10: Prctl handler (pc 51-56) ──
    p.append(_s(0x20, 16))                     # 51: LD [16] (arg0)
    p.append(_j(0x15, 38, 3, 0))               # 52: JEQ PR_SET_NO_NEW_PRIVS(38) → 56
    p.append(_j(0x15, 15, 2, 0))               # 53: JEQ PR_SET_NAME(15) → 56
    p.append(_j(0x15, 16, 1, 0))               # 54: JEQ PR_GET_NAME(16) → 56
    p.append(_s(0x06, 0x00050001))             # 55: RET ERRNO(1)
    p.append(_s(0x06, 0x7FFF0000))             # 56: RET ALLOW

    # ── Block 11: Special action returns ──
    p.append(_s(0x06, 0x7FFC0000))             # 57: RET LOG (ptrace)
    p.append(_s(0x06, 0x0005000D))             # 58: RET ERRNO(13) [EACCES] (mount)
    p.append(_s(0x06, 0x80000000))             # 59: RET KILL_PROCESS (vm_readv/writev)

    assert len(p) == 60, f"Expected 60 instructions, got {len(p)}"

    with open(out, 'wb') as f:
        for inst in p:
            f.write(inst)

    print(f"Generated {len(p)} instructions ({len(p)*8} bytes) -> {out}")


if __name__ == '__main__':
    generate(sys.argv[1])
