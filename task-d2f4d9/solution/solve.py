#!/usr/bin/env python3
"""
Complete solution for SECCOMP BPF Binary Filter Forensics task.

Decodes binary BPF filter files, analyzes them using the BPF simulator,
identifies security bugs, produces fixed binary filters, compiles and
runs the C SECCOMP test harness for verification.
"""

import json
import struct
import subprocess
import os
import sys

sys.path.insert(0, "/app")

SECCOMP_RET_ALLOW = 0x7FFF0000
SECCOMP_RET_KILL = 0x00000000
AUDIT_ARCH = 0xC000003E


def decode_binary_filter(path):
    """Decode a binary BPF filter file (sock_filter wire format) to instruction list."""
    with open(path, "rb") as f:
        data = f.read()
    insns = []
    for i in range(0, len(data), 8):
        code, jt, jf, k = struct.unpack_from("<HBBI", data, i)
        insns.append({"code": code, "jt": jt, "jf": jf, "k": k})
    return insns


def encode_binary_filter(insns, path):
    """Encode instruction list to binary BPF filter file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = bytearray()
    for insn in insns:
        data += struct.pack("<HBBI", insn["code"], insn["jt"], insn["jf"], insn["k"])
    with open(path, "wb") as f:
        f.write(data)


def make_data(nr, args=None):
    return {
        "nr": nr,
        "arch": AUDIT_ARCH,
        "instruction_pointer": 0,
        "args": args if args is not None else [0, 0, 0, 0, 0, 0],
    }


def main():
    from bpf_sim import simulate

    # ---- Step 1: Decode binary filters ----
    print("Decoding binary BPF filter files...")
    decoded = {}
    for name in ["stdio_mmap", "network_socket", "fs_readonly"]:
        decoded[name] = decode_binary_filter(f"/app/{name}.bpf")
        print(f"  {name}: {len(decoded[name])} instructions")

    with open("/app/decoded_filters.json", "w") as f:
        json.dump(decoded, f, indent=2)
    print("Wrote /app/decoded_filters.json")

    # ---- Step 2: Analyze each filter for bugs ----
    print("\nAnalyzing filters for security bugs...")
    audit = {}
    fixed_filters = {}

    # --- stdio_mmap ---
    insns = decoded["stdio_mmap"]
    test = make_data(9, [0, 4096, 5, 0x22, 0, 0])
    assert simulate(insns, test) == SECCOMP_RET_ALLOW, "Bug verification failed"

    fixed = [dict(i) for i in insns]
    fixed[7] = {"code": 32, "jt": 0, "jf": 0, "k": 32}
    assert simulate(fixed, test) == SECCOMP_RET_KILL, "Fix verification failed"
    assert simulate(fixed, make_data(9, [0, 4096, 3, 0x22, 0, 0])) == SECCOMP_RET_ALLOW
    assert simulate(fixed, make_data(0)) == SECCOMP_RET_ALLOW

    audit["stdio_mmap"] = {
        "buggy_instruction_index": 7,
        "description": (
            "Instruction 7 loads from seccomp_data offset 24 (args[1], the mmap length "
            "parameter) instead of offset 32 (args[2], the prot parameter). The PROT_EXEC "
            "bit test (JSET with k=4) is applied to the mmap length value rather than the "
            "protection flags. When the length does not happen to have bit 2 set (e.g., "
            "4096 = 0x1000), mmap calls requesting executable memory are incorrectly "
            "allowed, enabling code injection."
        ),
    }
    fixed_filters["stdio_mmap"] = fixed
    print("  stdio_mmap: bug at instruction 7 (wrong argument offset)")

    # --- network_socket ---
    insns = decoded["network_socket"]
    test = make_data(41, [10, 1, 0, 0, 0, 0])
    assert simulate(insns, test) == SECCOMP_RET_KILL, "Bug verification failed"

    fixed = [dict(i) for i in insns]
    fixed[10] = {"code": 21, "jt": 0, "jf": 5, "k": 10}
    assert simulate(fixed, test) == SECCOMP_RET_ALLOW, "Fix verification failed"
    assert simulate(fixed, make_data(41, [10, 2, 0, 0, 0, 0])) == SECCOMP_RET_ALLOW
    assert simulate(fixed, make_data(41, [2, 1, 0, 0, 0, 0])) == SECCOMP_RET_ALLOW
    assert simulate(fixed, make_data(41, [1, 1, 0, 0, 0, 0])) == SECCOMP_RET_KILL

    audit["network_socket"] = {
        "buggy_instruction_index": 10,
        "description": (
            "Instruction 10 (AF_INET6 domain check) has jt=1 instead of jt=0. When the "
            "domain matches AF_INET6 (10), the jump-true offset of 1 causes execution to "
            "skip instruction 11 (which loads args[1], the socket type) and land on "
            "instruction 12 (the AND mask). The accumulator still holds the domain value "
            "(10), which after masking with ~(SOCK_CLOEXEC|SOCK_NONBLOCK) remains 10. "
            "Since 10 is neither SOCK_STREAM (1) nor SOCK_DGRAM (2), all AF_INET6 socket "
            "creation is incorrectly denied."
        ),
    }
    fixed_filters["network_socket"] = fixed
    print("  network_socket: bug at instruction 10 (wrong jump target)")

    # --- fs_readonly ---
    insns = decoded["fs_readonly"]
    test = make_data(2, [0x7FFF0000, 1, 0, 0, 0, 0])
    assert simulate(insns, test) == SECCOMP_RET_ALLOW, "Bug verification failed"

    fixed = [dict(i) for i in insns]
    fixed[8] = {"code": 32, "jt": 0, "jf": 0, "k": 24}
    assert simulate(fixed, test) == SECCOMP_RET_KILL, "Fix verification failed"
    assert simulate(fixed, make_data(2, [0x7FFF0000, 2, 0, 0, 0, 0])) == SECCOMP_RET_KILL
    assert simulate(fixed, make_data(2, [0x7FFF0000, 0, 0, 0, 0, 0])) == SECCOMP_RET_ALLOW
    assert simulate(fixed, make_data(0)) == SECCOMP_RET_ALLOW

    audit["fs_readonly"] = {
        "buggy_instruction_index": 8,
        "description": (
            "Instruction 8 loads from seccomp_data offset 28 (the high 32 bits of args[1]) "
            "instead of offset 24 (the low 32 bits). On little-endian x86-64, 64-bit "
            "syscall arguments are stored with the low word at the base offset and the "
            "high word at base+4. Since open() flags like O_WRONLY (1) and O_RDWR (2) fit "
            "in 32 bits, the high word is always 0. The subsequent AND with O_ACCMODE (3) "
            "produces 0, which matches O_RDONLY, so all access modes bypass the filter."
        ),
    }
    fixed_filters["fs_readonly"] = fixed
    print("  fs_readonly: bug at instruction 8 (wrong 32-bit word of 64-bit argument)")

    # ---- Step 3: Write audit report ----
    with open("/app/audit.json", "w") as f:
        json.dump(audit, f, indent=2)
    print("\nWrote /app/audit.json")

    # ---- Step 4: Write fixed binary filters ----
    for name, insns in fixed_filters.items():
        path = f"/app/fixed/{name}.bpf"
        encode_binary_filter(insns, path)
        print(f"Wrote {path}")

    # ---- Step 5: Compile C SECCOMP test harness ----
    print("\nCompiling C SECCOMP test harness...")
    result = subprocess.run(
        ["make", "-C", "/app", "seccomp_loader"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("  Compilation successful")
    else:
        print(f"  Compilation failed: {result.stderr}")

    # ---- Step 6: Run verification tests with C harness ----
    print("\nRunning verification with C SECCOMP harness...")
    verify_lines = []

    test_cases = [
        # (filter, syscall_nr, args, description)
        ("fixed/stdio_mmap.bpf", 0, [0, 0, 0], "read - expect ALLOW"),
        ("fixed/stdio_mmap.bpf", 1, [0, 0, 0], "write - expect ALLOW"),
        ("fixed/stdio_mmap.bpf", 9, [0, 4096, 1], "mmap PROT_READ - expect ALLOW"),
        ("fixed/stdio_mmap.bpf", 9, [0, 4096, 5], "mmap PROT_READ|PROT_EXEC - expect KILL"),
        ("fixed/stdio_mmap.bpf", 59, [0, 0, 0], "execve - expect KILL"),
        ("fixed/network_socket.bpf", 41, [2, 1, 0], "socket AF_INET STREAM - expect ALLOW"),
        ("fixed/network_socket.bpf", 41, [10, 1, 0], "socket AF_INET6 STREAM - expect ALLOW"),
        ("fixed/network_socket.bpf", 41, [1, 1, 0], "socket AF_UNIX - expect KILL"),
        ("fixed/network_socket.bpf", 41, [2, 3, 0], "socket AF_INET RAW - expect KILL"),
        ("fixed/fs_readonly.bpf", 2, [0x7FFF0000, 0, 0], "open O_RDONLY - expect ALLOW"),
        ("fixed/fs_readonly.bpf", 2, [0x7FFF0000, 1, 0], "open O_WRONLY - expect KILL"),
        ("fixed/fs_readonly.bpf", 2, [0x7FFF0000, 2, 0], "open O_RDWR - expect KILL"),
    ]

    loader = "/app/seccomp_loader"
    if os.path.exists(loader):
        for bpf_file, nr, args, desc in test_cases:
            cmd = [loader, f"/app/{bpf_file}", str(nr)] + [str(a) for a in args]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                output = r.stdout.strip()
                line = f"[{desc}] {output}"
            except subprocess.TimeoutExpired:
                line = f"[{desc}] TIMEOUT"
            except Exception as e:
                line = f"[{desc}] ERROR: {e}"
            verify_lines.append(line)
            print(f"  {line}")
    else:
        verify_lines.append("C harness not available — compilation may have failed")
        verify_lines.append("Verification done via Python BPF simulator instead")
        for bpf_file, nr, args, desc in test_cases:
            padded_args = args + [0] * (6 - len(args))
            insns = decode_binary_filter(f"/app/{bpf_file}")
            result = simulate(insns, make_data(nr, padded_args))
            action = "ALLOW" if result == SECCOMP_RET_ALLOW else "KILL"
            line = f"[{desc}] simulator result={action}"
            verify_lines.append(line)
            print(f"  {line}")

    with open("/app/verify_output.txt", "w") as f:
        f.write("\n".join(verify_lines) + "\n")
    print("\nWrote /app/verify_output.txt")
    print("All tasks complete.")


if __name__ == "__main__":
    main()
