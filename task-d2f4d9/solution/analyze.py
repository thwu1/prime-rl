#!/usr/bin/env python3
"""
Analyze buggy SECCOMP BPF filters, identify vulnerabilities, and produce fixes.

This script uses the BPF simulator to verify that each buggy filter deviates
from its intended policy, identifies the faulty instruction, and generates
corrected filter programs.
"""
import json
import sys

sys.path.insert(0, '/app')
from bpf_sim import simulate

SECCOMP_RET_ALLOW = 0x7FFF0000
SECCOMP_RET_KILL = 0x00000000
AUDIT_ARCH = 0xC000003E


def make_data(nr, args=None):
    return {
        "nr": nr,
        "arch": AUDIT_ARCH,
        "instruction_pointer": 0,
        "args": args if args is not None else [0, 0, 0, 0, 0, 0],
    }


def analyze_stdio_mmap(filt):
    """Analyze the stdio_mmap filter for the mmap PROT_EXEC bypass bug."""
    insns = filt['instructions']

    # Verify bug: mmap with PROT_READ|PROT_EXEC (prot=5) should be KILL
    # but length=4096 has no bit 2, so buggy filter ALLOWs it
    test_data = make_data(9, [0, 4096, 5, 0x22, 0, 0])
    result = simulate(insns, test_data)
    assert result == SECCOMP_RET_ALLOW, "Expected bug: mmap PROT_EXEC should be incorrectly allowed"

    # Identify the bug: instruction 7 loads from offset 24 (args[1]=length)
    # instead of offset 32 (args[2]=prot)
    buggy_idx = 7
    assert insns[buggy_idx]['k'] == 24, f"Expected buggy offset 24, got {insns[buggy_idx]['k']}"

    # For mmap(addr, length, prot, flags, fd, offset):
    #   args[2] = prot, which is at seccomp_data offset 16 + 2*8 = 32
    fixed_insns = [dict(d) for d in insns]
    fixed_insns[buggy_idx] = {"code": 32, "jt": 0, "jf": 0, "k": 32}

    # Verify fix works
    assert simulate(fixed_insns, test_data) == SECCOMP_RET_KILL, "Fix failed: should KILL PROT_EXEC"
    assert simulate(fixed_insns, make_data(9, [0, 4096, 3, 0x22, 0, 0])) == SECCOMP_RET_ALLOW, \
        "Fix regression: should ALLOW PROT_READ|PROT_WRITE"
    assert simulate(fixed_insns, make_data(0)) == SECCOMP_RET_ALLOW, "Fix regression: should ALLOW read"

    description = (
        f"Instruction {buggy_idx} loads from seccomp_data offset {insns[buggy_idx]['k']} "
        f"(args[1], the length parameter of mmap) instead of offset 32 (args[2], the prot parameter). "
        "The PROT_EXEC bit test (JSET with k=4) is applied to the mmap length value rather than "
        "the protection flags. When the length does not happen to have bit 2 set (e.g., 4096 = 0x1000), "
        "mmap calls requesting executable memory are incorrectly allowed, enabling code injection."
    )

    return buggy_idx, description, fixed_insns


def analyze_network_socket(filt):
    """Analyze the network_socket filter for the AF_INET6 jump target bug."""
    insns = filt['instructions']

    # Verify bug: socket(AF_INET6, SOCK_STREAM, 0) should be ALLOW but is KILL
    test_data = make_data(41, [10, 1, 0, 0, 0, 0])
    result = simulate(insns, test_data)
    assert result == SECCOMP_RET_KILL, "Expected bug: AF_INET6 SOCK_STREAM should be incorrectly killed"

    # Identify the bug: instruction 10 (AF_INET6 check) has jt=1 instead of jt=0
    # jt=1 skips the load of args[1] and jumps directly to the AND mask operation,
    # causing the stale accumulator (domain value 10) to be compared against socket types
    buggy_idx = 10
    assert insns[buggy_idx]['jt'] == 1, f"Expected buggy jt=1, got {insns[buggy_idx]['jt']}"

    # Fix: set jt=0 so AF_INET6 match falls through to load args[1] (type)
    fixed_insns = [dict(d) for d in insns]
    fixed_insns[buggy_idx] = {"code": 21, "jt": 0, "jf": 5, "k": 10}

    # Verify fix works
    assert simulate(fixed_insns, test_data) == SECCOMP_RET_ALLOW, "Fix failed: AF_INET6 SOCK_STREAM should ALLOW"
    assert simulate(fixed_insns, make_data(41, [10, 2, 0, 0, 0, 0])) == SECCOMP_RET_ALLOW, \
        "Fix failed: AF_INET6 SOCK_DGRAM should ALLOW"
    assert simulate(fixed_insns, make_data(41, [2, 1, 0, 0, 0, 0])) == SECCOMP_RET_ALLOW, \
        "Fix regression: AF_INET SOCK_STREAM should still ALLOW"
    assert simulate(fixed_insns, make_data(41, [1, 1, 0, 0, 0, 0])) == SECCOMP_RET_KILL, \
        "Fix regression: AF_UNIX should still KILL"

    description = (
        f"Instruction {buggy_idx} (AF_INET6 domain check) has jt={insns[buggy_idx]['jt']} "
        "instead of jt=0. When the domain matches AF_INET6 (10), the jump-true offset of 1 "
        "causes execution to skip instruction 11 (which loads args[1], the socket type) and "
        "land on instruction 12 (the AND mask). The accumulator still holds the domain value (10), "
        "which after masking with ~(SOCK_CLOEXEC|SOCK_NONBLOCK) remains 10. Since 10 is neither "
        "SOCK_STREAM (1) nor SOCK_DGRAM (2), all AF_INET6 socket creation is incorrectly denied."
    )

    return buggy_idx, description, fixed_insns


def analyze_fs_readonly(filt):
    """Analyze the fs_readonly filter for the 64-bit argument word confusion bug."""
    insns = filt['instructions']

    # Verify bug: open(path, O_WRONLY, 0) should be KILL but is ALLOW
    test_data = make_data(2, [0x7FFF0000, 1, 0, 0, 0, 0])
    result = simulate(insns, test_data)
    assert result == SECCOMP_RET_ALLOW, "Expected bug: open O_WRONLY should be incorrectly allowed"

    # Identify the bug: instruction 8 loads from offset 28 (HIGH 32 bits of args[1])
    # instead of offset 24 (LOW 32 bits of args[1]).
    # On little-endian x86-64, the actual flags value is in the low 32 bits.
    # The high 32 bits are always 0 for typical flag values, so O_ACCMODE check always sees 0.
    buggy_idx = 8
    assert insns[buggy_idx]['k'] == 28, f"Expected buggy offset 28, got {insns[buggy_idx]['k']}"

    # Fix: change offset from 28 to 24 to load the correct (low) 32-bit word
    fixed_insns = [dict(d) for d in insns]
    fixed_insns[buggy_idx] = {"code": 32, "jt": 0, "jf": 0, "k": 24}

    # Verify fix works
    assert simulate(fixed_insns, test_data) == SECCOMP_RET_KILL, "Fix failed: O_WRONLY should KILL"
    assert simulate(fixed_insns, make_data(2, [0x7FFF0000, 2, 0, 0, 0, 0])) == SECCOMP_RET_KILL, \
        "Fix failed: O_RDWR should KILL"
    assert simulate(fixed_insns, make_data(2, [0x7FFF0000, 0, 0, 0, 0, 0])) == SECCOMP_RET_ALLOW, \
        "Fix regression: O_RDONLY should ALLOW"
    assert simulate(fixed_insns, make_data(0)) == SECCOMP_RET_ALLOW, "Fix regression: read should ALLOW"

    description = (
        f"Instruction {buggy_idx} loads from seccomp_data offset {insns[buggy_idx]['k']} "
        "(the high 32 bits of args[1]) instead of offset 24 (the low 32 bits). "
        "On little-endian x86-64, 64-bit syscall arguments are stored with the low word at the "
        "base offset and the high word at base+4. Since open() flags like O_WRONLY (1) and O_RDWR (2) "
        "fit in 32 bits, the high word is always 0. The subsequent AND with O_ACCMODE (3) produces 0, "
        "which matches O_RDONLY, so all access modes bypass the filter — including writable opens."
    )

    return buggy_idx, description, fixed_insns


def main():
    with open('/app/filters.json') as f:
        data = json.load(f)

    filters = data['filters']
    audit = {}
    fixed_filters = {}

    analyzers = [
        ("stdio_mmap", analyze_stdio_mmap),
        ("network_socket", analyze_network_socket),
        ("fs_readonly", analyze_fs_readonly),
    ]

    for name, analyzer in analyzers:
        buggy_idx, description, fixed_insns = analyzer(filters[name])
        audit[name] = {
            "buggy_instruction_index": buggy_idx,
            "description": description,
        }
        fixed_filters[name] = {"instructions": fixed_insns}
        print(f"  {name}: bug at instruction {buggy_idx}")

    with open('/app/audit.json', 'w') as f:
        json.dump(audit, f, indent=2)

    with open('/app/fixed_filters.json', 'w') as f:
        json.dump(fixed_filters, f, indent=2)

    print("Analysis complete. Output: /app/audit.json, /app/fixed_filters.json")


if __name__ == '__main__':
    main()
