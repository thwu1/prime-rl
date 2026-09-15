"""
BPF filter verification tests.

Implements a minimal cBPF simulator matching the Linux seccomp filter
execution model, then checks the compiled filter against expected verdicts.

"""

import struct
import os
import pytest

# ---------- Constants ----------

AUDIT_ARCH_X86_64 = 0xC000003E

# seccomp_data layout (little-endian x86_64):
#   offset 0: nr (uint32)
#   offset 4: arch (uint32)
#   offset 8: instruction_pointer (uint64)
#  offset 16: args[0] (uint64) ... args[5] (uint64)
# Total: 16 + 6*8 = 64 bytes

SECCOMP_RET_KILL_THREAD  = 0x00000000
SECCOMP_RET_KILL_PROCESS = 0x80000000
SECCOMP_RET_TRAP         = 0x00030000
SECCOMP_RET_ERRNO        = 0x00050000
SECCOMP_RET_TRACE        = 0x7FF00000
SECCOMP_RET_LOG          = 0x7FFC0000
SECCOMP_RET_ALLOW        = 0x7FFF0000
SECCOMP_RET_ACTION_FULL  = 0xFFFF0000
SECCOMP_RET_DATA         = 0x0000FFFF

# BPF instruction classes
BPF_LD   = 0x00
BPF_LDX  = 0x01
BPF_ST   = 0x02
BPF_STX  = 0x03
BPF_ALU  = 0x04
BPF_JMP  = 0x05
BPF_RET  = 0x06
BPF_MISC = 0x07
BPF_CLASS_MASK = 0x07

# BPF LD/LDX modes
BPF_IMM = 0x00
BPF_ABS = 0x20
BPF_IND = 0x40
BPF_MEM = 0x60
BPF_LEN = 0x80
BPF_MSH = 0xa0

# BPF sizes
BPF_W = 0x00
BPF_H = 0x08
BPF_B = 0x10

# BPF ALU ops
BPF_ADD = 0x00
BPF_SUB = 0x10
BPF_MUL = 0x20
BPF_DIV = 0x30
BPF_OR  = 0x40
BPF_AND = 0x50
BPF_LSH = 0x60
BPF_RSH = 0x70
BPF_NEG = 0x80
BPF_MOD = 0x90
BPF_XOR = 0xa0

# BPF JMP ops
BPF_JA   = 0x00
BPF_JEQ  = 0x10
BPF_JGT  = 0x20
BPF_JGE  = 0x30
BPF_JSET = 0x40

# BPF source
BPF_K = 0x00
BPF_X = 0x08
BPF_A = 0x10


def build_seccomp_data(nr, arch, args=None):
    """Build a 64-byte seccomp_data struct (little-endian)."""
    if args is None:
        args = [0] * 6
    while len(args) < 6:
        args.append(0)
    # nr: uint32, arch: uint32, ip: uint64, args[6]: uint64 each
    data = struct.pack('<IIQ', nr, arch, 0)
    for a in args:
        data += struct.pack('<Q', a)
    assert len(data) == 64
    return data


def load_bpf_program(path):
    """Load a binary BPF program (array of sock_filter)."""
    with open(path, 'rb') as f:
        raw = f.read()
    # Each instruction is 8 bytes: uint16 code, uint8 jt, uint8 jf, uint32 k
    n = len(raw) // 8
    insns = []
    for i in range(n):
        code, jt, jf, k = struct.unpack_from('<HBBI', raw, i * 8)
        insns.append((code, jt, jf, k))
    return insns


def simulate_bpf(insns, data):
    """
    Simulate a cBPF program on the given seccomp_data.
    Returns the SECCOMP_RET_xxx value, or raises on fault.
    """
    acc = 0
    ip = 0
    scratch = [0] * 16  # BPF_MEMWORDS
    max_steps = 10000

    while ip < len(insns) and max_steps > 0:
        max_steps -= 1
        code, jt, jf, k = insns[ip]
        cls = code & BPF_CLASS_MASK
        ip += 1

        if cls == BPF_LD:
            mode = code & 0xe0
            if mode == BPF_ABS:
                if k + 4 > len(data):
                    raise RuntimeError(f"BPF LD ABS out of range: offset={k}")
                acc = struct.unpack_from('<I', data, k)[0]
            elif mode == BPF_IMM:
                acc = k
            elif mode == BPF_MEM:
                acc = scratch[k]
            else:
                raise RuntimeError(f"Unsupported BPF_LD mode: 0x{mode:02x}")

        elif cls == BPF_ALU:
            op = code & 0xf0
            if op == BPF_AND:
                acc = acc & k
            elif op == BPF_OR:
                acc = acc | k
            elif op == BPF_ADD:
                acc = (acc + k) & 0xFFFFFFFF
            elif op == BPF_SUB:
                acc = (acc - k) & 0xFFFFFFFF
            elif op == BPF_RSH:
                acc = acc >> k
            elif op == BPF_LSH:
                acc = (acc << k) & 0xFFFFFFFF
            elif op == BPF_NEG:
                acc = (-acc) & 0xFFFFFFFF
            elif op == BPF_XOR:
                acc = acc ^ k
            else:
                raise RuntimeError(f"Unsupported BPF_ALU op: 0x{op:02x}")

        elif cls == BPF_JMP:
            op = code & 0xf0
            if op == BPF_JA:
                ip += k
            elif op == BPF_JEQ:
                ip += jt if acc == k else jf
            elif op == BPF_JGT:
                ip += jt if acc > k else jf
            elif op == BPF_JGE:
                ip += jt if acc >= k else jf
            elif op == BPF_JSET:
                ip += jt if (acc & k) != 0 else jf
            else:
                raise RuntimeError(f"Unsupported BPF_JMP op: 0x{op:02x}")

        elif cls == BPF_RET:
            return k

        elif cls == BPF_ST:
            scratch[k] = acc

        elif cls == BPF_MISC:
            pass  # TAX/TXA not needed for seccomp

        else:
            raise RuntimeError(f"Unknown BPF class: 0x{cls:02x}")

    raise RuntimeError("BPF program fell off end or exceeded step limit")


def action_name(val):
    """Convert a SECCOMP_RET value to a human-readable string."""
    act = val & SECCOMP_RET_ACTION_FULL
    data = val & SECCOMP_RET_DATA
    names = {
        SECCOMP_RET_KILL_THREAD: "KILL",
        SECCOMP_RET_KILL_PROCESS: "KILL_PROCESS",
        SECCOMP_RET_TRAP: "TRAP",
        SECCOMP_RET_LOG: "LOG",
        SECCOMP_RET_ALLOW: "ALLOW",
    }
    if act == SECCOMP_RET_ERRNO:
        return f"ERRNO({data})"
    if act == SECCOMP_RET_TRACE:
        return f"TRACE({data})"
    return names.get(act, f"0x{val:08x}")


# ---------- Load the filter ----------

BPF_PATH = "/app/filter.bpf"


@pytest.fixture(scope="module")
def bpf_insns():
    assert os.path.exists(BPF_PATH), f"BPF filter not found at {BPF_PATH}"
    insns = load_bpf_program(BPF_PATH)
    assert len(insns) > 0, "BPF program is empty"
    return insns


def run_filter(bpf_insns, syscall_nr, args=None):
    data = build_seccomp_data(syscall_nr, AUDIT_ARCH_X86_64, args)
    return simulate_bpf(bpf_insns, data)


# ---------- Architecture validation ----------

class TestArchValidation:
    def test_correct_arch_allows_processing(self, bpf_insns):
        """x86_64 arch should not be killed by arch check."""
        data = build_seccomp_data(0, AUDIT_ARCH_X86_64, [0]*6)  # read
        result = simulate_bpf(bpf_insns, data)
        assert result == SECCOMP_RET_ALLOW

    def test_wrong_arch_killed(self, bpf_insns):
        """Non-x86_64 arch should be killed."""
        AUDIT_ARCH_I386 = 0x40000003
        data = build_seccomp_data(0, AUDIT_ARCH_I386, [0]*6)
        result = simulate_bpf(bpf_insns, data)
        assert result == SECCOMP_RET_KILL_THREAD

    def test_wrong_arch_arm(self, bpf_insns):
        """ARM arch should be killed."""
        AUDIT_ARCH_ARM = 0x40000028
        data = build_seccomp_data(0, AUDIT_ARCH_ARM, [0]*6)
        result = simulate_bpf(bpf_insns, data)
        assert result == SECCOMP_RET_KILL_THREAD

    def test_zero_arch_killed(self, bpf_insns):
        """Zero arch should be killed."""
        data = build_seccomp_data(0, 0, [0]*6)
        result = simulate_bpf(bpf_insns, data)
        assert result == SECCOMP_RET_KILL_THREAD


# ---------- Basic syscall allows ----------

class TestBasicAllows:
    @pytest.mark.parametrize("name,nr", [
        ("read", 0),
        ("write", 1),
        ("close", 3),
        ("rt_sigreturn", 15),
        ("exit", 60),
        ("exit_group", 231),
        ("brk", 12),
        ("mmap", 9),
        ("munmap", 11),
        ("rt_sigaction", 13),
        ("rt_sigprocmask", 14),
        ("gettid", 186),
        ("getpid", 39),
        ("set_tid_address", 218),
        ("set_robust_list", 273),
        ("rseq", 334),
        ("futex", 202),
        ("clock_gettime", 228),
        ("getrandom", 318),
        ("sigaltstack", 131),
        ("prlimit64", 302),
        ("newfstatat", 262),
    ])
    def test_allowed_syscall(self, bpf_insns, name, nr):
        result = run_filter(bpf_insns, nr)
        assert result == SECCOMP_RET_ALLOW, \
            f"{name} (nr={nr}) should be ALLOW, got {action_name(result)}"


# ---------- Default action (KILL) ----------

class TestDefaultAction:
    @pytest.mark.parametrize("nr", [
        999,   # non-existent
        2,     # open (not in policy)
        4,     # stat
        6,     # lstat
        7,     # poll
    ])
    def test_unlisted_syscall_killed(self, bpf_insns, nr):
        result = run_filter(bpf_insns, nr)
        assert result == SECCOMP_RET_KILL_THREAD, \
            f"Syscall {nr} should be KILL, got {action_name(result)}"


# ---------- Non-ALLOW actions ----------

class TestActions:
    def test_access_logged(self, bpf_insns):
        result = run_filter(bpf_insns, 21)  # access
        assert result == SECCOMP_RET_LOG

    def test_socket_errno(self, bpf_insns):
        result = run_filter(bpf_insns, 41)  # socket
        assert result == (SECCOMP_RET_ERRNO | 1), \
            f"socket should be ERRNO(1), got {action_name(result)}"

    def test_execve_kill_process(self, bpf_insns):
        result = run_filter(bpf_insns, 59)  # execve
        assert result == SECCOMP_RET_KILL_PROCESS

    def test_arch_prctl_trace(self, bpf_insns):
        result = run_filter(bpf_insns, 158)  # arch_prctl
        assert result == (SECCOMP_RET_TRACE | 42), \
            f"arch_prctl should be TRACE(42), got {action_name(result)}"


# ---------- Argument comparisons ----------

class TestArgComparisons:
    # openat: ALLOW only if (arg2 & 0x3) == (0x100 & 0x3) == 0 (O_RDONLY)
    def test_openat_rdonly_allowed(self, bpf_insns):
        """openat with O_RDONLY (flags & 0x3 == 0) should ALLOW."""
        result = run_filter(bpf_insns, 257, [0, 0, 0, 0, 0, 0])
        assert result == SECCOMP_RET_ALLOW

    def test_openat_rdonly_with_cloexec(self, bpf_insns):
        """openat with O_RDONLY|O_CLOEXEC (0x80000) should ALLOW."""
        result = run_filter(bpf_insns, 257, [0, 0, 0x80000, 0, 0, 0])
        assert result == SECCOMP_RET_ALLOW

    def test_openat_wronly_killed(self, bpf_insns):
        """openat with O_WRONLY (flags=1, 1 & 0x3 != 0) should KILL."""
        result = run_filter(bpf_insns, 257, [0, 0, 1, 0, 0, 0])
        assert result == SECCOMP_RET_KILL_THREAD

    def test_openat_rdwr_killed(self, bpf_insns):
        """openat with O_RDWR (flags=2, 2 & 0x3 != 0) should KILL."""
        result = run_filter(bpf_insns, 257, [0, 0, 2, 0, 0, 0])
        assert result == SECCOMP_RET_KILL_THREAD

    def test_openat_flags_3_killed(self, bpf_insns):
        """openat with flags=3 (3 & 0x3 != 0) should KILL."""
        result = run_filter(bpf_insns, 257, [0, 0, 3, 0, 0, 0])
        assert result == SECCOMP_RET_KILL_THREAD

    # ioctl: ALLOW only if arg0 == 1
    def test_ioctl_stdout_allowed(self, bpf_insns):
        result = run_filter(bpf_insns, 16, [1, 0, 0, 0, 0, 0])
        assert result == SECCOMP_RET_ALLOW

    def test_ioctl_other_fd_killed(self, bpf_insns):
        result = run_filter(bpf_insns, 16, [0, 0, 0, 0, 0, 0])
        assert result == SECCOMP_RET_KILL_THREAD

    def test_ioctl_fd2_killed(self, bpf_insns):
        result = run_filter(bpf_insns, 16, [2, 0, 0, 0, 0, 0])
        assert result == SECCOMP_RET_KILL_THREAD

    # fcntl: ALLOW if arg1 == 1 (F_GETFD) or arg1 == 3 (F_GETFL)
    def test_fcntl_getfd_allowed(self, bpf_insns):
        result = run_filter(bpf_insns, 72, [0, 1, 0, 0, 0, 0])
        assert result == SECCOMP_RET_ALLOW

    def test_fcntl_getfl_allowed(self, bpf_insns):
        result = run_filter(bpf_insns, 72, [0, 3, 0, 0, 0, 0])
        assert result == SECCOMP_RET_ALLOW

    def test_fcntl_setfd_killed(self, bpf_insns):
        """fcntl with F_SETFD (arg1=2) should KILL."""
        result = run_filter(bpf_insns, 72, [0, 2, 0, 0, 0, 0])
        assert result == SECCOMP_RET_KILL_THREAD

    def test_fcntl_other_killed(self, bpf_insns):
        """fcntl with unknown cmd should KILL."""
        result = run_filter(bpf_insns, 72, [0, 99, 0, 0, 0, 0])
        assert result == SECCOMP_RET_KILL_THREAD

    # prctl: ALLOW only if arg0 == 15 (PR_SET_NAME)
    def test_prctl_set_name_allowed(self, bpf_insns):
        result = run_filter(bpf_insns, 157, [15, 0, 0, 0, 0, 0])
        assert result == SECCOMP_RET_ALLOW

    def test_prctl_other_killed(self, bpf_insns):
        result = run_filter(bpf_insns, 157, [0, 0, 0, 0, 0, 0])
        assert result == SECCOMP_RET_KILL_THREAD

    def test_prctl_seccomp_killed(self, bpf_insns):
        """prctl with PR_SET_SECCOMP (arg0=22) should KILL."""
        result = run_filter(bpf_insns, 157, [22, 0, 0, 0, 0, 0])
        assert result == SECCOMP_RET_KILL_THREAD

    # mprotect: ALLOW if arg2 != 7 (NE comparison)
    def test_mprotect_prot_none_allowed(self, bpf_insns):
        """mprotect with PROT_NONE (arg2=0) should ALLOW."""
        result = run_filter(bpf_insns, 10, [0, 0, 0, 0, 0, 0])
        assert result == SECCOMP_RET_ALLOW

    def test_mprotect_rw_allowed(self, bpf_insns):
        """mprotect with PROT_READ|PROT_WRITE (arg2=3) should ALLOW."""
        result = run_filter(bpf_insns, 10, [0, 0, 3, 0, 0, 0])
        assert result == SECCOMP_RET_ALLOW

    def test_mprotect_rwx_killed(self, bpf_insns):
        """mprotect with PROT_READ|PROT_WRITE|PROT_EXEC (arg2=7) should KILL."""
        result = run_filter(bpf_insns, 10, [0, 0, 7, 0, 0, 0])
        assert result == SECCOMP_RET_KILL_THREAD

    def test_mprotect_rx_allowed(self, bpf_insns):
        """mprotect with PROT_READ|PROT_EXEC (arg2=5) should ALLOW."""
        result = run_filter(bpf_insns, 10, [0, 0, 5, 0, 0, 0])
        assert result == SECCOMP_RET_ALLOW

    def test_mprotect_wx_allowed(self, bpf_insns):
        """mprotect with PROT_WRITE|PROT_EXEC (arg2=6) should ALLOW."""
        result = run_filter(bpf_insns, 10, [0, 0, 6, 0, 0, 0])
        assert result == SECCOMP_RET_ALLOW


# ---------- 64-bit argument handling ----------

class TestArg64Bit:
    # statx: ALLOW if arg2 >= 0x100000000 (requires 64-bit comparison)
    def test_statx_high_flags_allowed(self, bpf_insns):
        """statx with arg2=0x100000000 (high bit set) should ALLOW."""
        result = run_filter(bpf_insns, 332, [0, 0, 0x100000000, 0, 0, 0])
        assert result == SECCOMP_RET_ALLOW

    def test_statx_very_high_flags_allowed(self, bpf_insns):
        """statx with arg2=0x200000000 should ALLOW."""
        result = run_filter(bpf_insns, 332, [0, 0, 0x200000000, 0, 0, 0])
        assert result == SECCOMP_RET_ALLOW

    def test_statx_low_flags_killed(self, bpf_insns):
        """statx with arg2=0 should KILL (below threshold)."""
        result = run_filter(bpf_insns, 332, [0, 0, 0, 0, 0, 0])
        assert result == SECCOMP_RET_KILL_THREAD

    def test_statx_just_below_killed(self, bpf_insns):
        """statx with arg2=0xFFFFFFFF (just below 0x100000000) should KILL."""
        result = run_filter(bpf_insns, 332, [0, 0, 0xFFFFFFFF, 0, 0, 0])
        assert result == SECCOMP_RET_KILL_THREAD

    def test_statx_max_value_allowed(self, bpf_insns):
        """statx with arg2=0xFFFFFFFFFFFFFFFF should ALLOW."""
        result = run_filter(bpf_insns, 332, [0, 0, 0xFFFFFFFFFFFFFFFF, 0, 0, 0])
        assert result == SECCOMP_RET_ALLOW

    # fstatfs: ALLOW if arg1 != 0x200000001 (64-bit NE comparison)
    def test_fstatfs_allowed_zero(self, bpf_insns):
        """fstatfs with arg1=0 should ALLOW (NE is true)."""
        result = run_filter(bpf_insns, 138, [0, 0, 0, 0, 0, 0])
        assert result == SECCOMP_RET_ALLOW

    def test_fstatfs_killed_exact_match(self, bpf_insns):
        """fstatfs with arg1=0x200000001 should KILL (exact match, NE false)."""
        result = run_filter(bpf_insns, 138, [0, 0x200000001, 0, 0, 0, 0])
        assert result == SECCOMP_RET_KILL_THREAD

    def test_fstatfs_allowed_lo_differs(self, bpf_insns):
        """fstatfs with arg1=0x200000000 should ALLOW (lo word differs)."""
        result = run_filter(bpf_insns, 138, [0, 0x200000000, 0, 0, 0, 0])
        assert result == SECCOMP_RET_ALLOW

    def test_fstatfs_allowed_hi_differs(self, bpf_insns):
        """fstatfs with arg1=0x100000001 should ALLOW (hi word differs)."""
        result = run_filter(bpf_insns, 138, [0, 0x100000001, 0, 0, 0, 0])
        assert result == SECCOMP_RET_ALLOW


# ---------- Multi-rule syscall handling ----------

class TestMultiRuleSyscall:
    """fcntl has two rules: arg1==1 and arg1==3. Both must work."""
    def test_first_rule_matches(self, bpf_insns):
        result = run_filter(bpf_insns, 72, [0, 1, 0, 0, 0, 0])
        assert result == SECCOMP_RET_ALLOW

    def test_second_rule_matches(self, bpf_insns):
        """Second rule (arg1==3) must be reachable after first rule fails."""
        result = run_filter(bpf_insns, 72, [0, 3, 0, 0, 0, 0])
        assert result == SECCOMP_RET_ALLOW

    def test_neither_rule_matches(self, bpf_insns):
        result = run_filter(bpf_insns, 72, [0, 5, 0, 0, 0, 0])
        assert result == SECCOMP_RET_KILL_THREAD


# ---------- Multi-argument constraints ----------

class TestMultiArgConstraint:
    """clone3: ALLOW only if arg0 == 0 AND arg1 >= 56."""
    def test_both_args_match(self, bpf_insns):
        """clone3(flags=0, size=56) should ALLOW."""
        result = run_filter(bpf_insns, 435, [0, 56, 0, 0, 0, 0])
        assert result == SECCOMP_RET_ALLOW

    def test_large_size(self, bpf_insns):
        """clone3(flags=0, size=100) should ALLOW."""
        result = run_filter(bpf_insns, 435, [0, 100, 0, 0, 0, 0])
        assert result == SECCOMP_RET_ALLOW

    def test_wrong_flags(self, bpf_insns):
        """clone3(flags=1, size=56) should KILL (arg0 != 0)."""
        result = run_filter(bpf_insns, 435, [1, 56, 0, 0, 0, 0])
        assert result == SECCOMP_RET_KILL_THREAD

    def test_size_too_small(self, bpf_insns):
        """clone3(flags=0, size=55) should KILL (arg1 < 56)."""
        result = run_filter(bpf_insns, 435, [0, 55, 0, 0, 0, 0])
        assert result == SECCOMP_RET_KILL_THREAD

    def test_zero_size(self, bpf_insns):
        """clone3(flags=0, size=0) should KILL."""
        result = run_filter(bpf_insns, 435, [0, 0, 0, 0, 0, 0])
        assert result == SECCOMP_RET_KILL_THREAD

    def test_both_args_wrong(self, bpf_insns):
        """clone3(flags=2, size=10) should KILL."""
        result = run_filter(bpf_insns, 435, [2, 10, 0, 0, 0, 0])
        assert result == SECCOMP_RET_KILL_THREAD


# ---------- Edge cases ----------

class TestEdgeCases:
    def test_high_syscall_number_killed(self, bpf_insns):
        """Very high syscall number should hit default KILL."""
        result = run_filter(bpf_insns, 0x7FFFFFFF)
        assert result == SECCOMP_RET_KILL_THREAD

    def test_ioctl_large_fd_killed(self, bpf_insns):
        """ioctl with a large fd value should still be killed."""
        result = run_filter(bpf_insns, 16, [0x80000000, 0, 0, 0, 0, 0])
        assert result == SECCOMP_RET_KILL_THREAD

    def test_openat_large_flags_rdonly(self, bpf_insns):
        """openat with large flags but low bits clear should ALLOW."""
        result = run_filter(bpf_insns, 257, [0, 0, 0xFFFF0000, 0, 0, 0])
        assert result == SECCOMP_RET_ALLOW

    def test_masked_eq_all_zero(self, bpf_insns):
        """openat mask check: 0 & 0x3 == 0x100 & 0x3 => 0 == 0 => match."""
        result = run_filter(bpf_insns, 257, [0, 0, 0, 0, 0, 0])
        assert result == SECCOMP_RET_ALLOW

    def test_masked_eq_value_4(self, bpf_insns):
        """openat mask check: 4 & 0x3 == 0x100 & 0x3 => 0 == 0 => match."""
        result = run_filter(bpf_insns, 257, [0, 0, 4, 0, 0, 0])
        assert result == SECCOMP_RET_ALLOW
