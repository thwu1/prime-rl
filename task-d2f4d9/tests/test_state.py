
import json
import struct
import os
import subprocess
import importlib.util
import pytest

SECCOMP_RET_ALLOW = 0x7FFF0000
SECCOMP_RET_KILL = 0x00000000
AUDIT_ARCH_X86_64 = 0xC000003E


def load_simulator():
    """Import the agent's BPF simulator from /app/bpf_sim.py."""
    spec = importlib.util.spec_from_file_location("bpf_sim", "/app/bpf_sim.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.simulate


def make_seccomp_data(nr, args=None):
    """Create a seccomp_data dict for testing."""
    if args is None:
        args = [0, 0, 0, 0, 0, 0]
    return {
        "nr": nr,
        "arch": AUDIT_ARCH_X86_64,
        "instruction_pointer": 0,
        "args": args,
    }


def decode_binary_filter(path):
    """Decode a binary BPF filter file to instruction list."""
    with open(path, "rb") as f:
        data = f.read()
    insns = []
    for i in range(0, len(data), 8):
        code, jt, jf, k = struct.unpack_from("<HBBI", data, i)
        insns.append({"code": code, "jt": jt, "jf": jf, "k": k})
    return insns


# ============================================================
# Test Suite 1: BPF Simulator Correctness
# ============================================================


class TestSimulatorBasic:
    """Verify the BPF simulator handles all required opcodes correctly."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.simulate = load_simulator()

    def test_ret_allow(self):
        prog = [{"code": 6, "jt": 0, "jf": 0, "k": SECCOMP_RET_ALLOW}]
        assert self.simulate(prog, make_seccomp_data(0)) == SECCOMP_RET_ALLOW

    def test_ret_kill(self):
        prog = [{"code": 6, "jt": 0, "jf": 0, "k": SECCOMP_RET_KILL}]
        assert self.simulate(prog, make_seccomp_data(0)) == SECCOMP_RET_KILL

    def test_load_nr_and_jeq(self):
        """Load syscall nr, check equality, branch accordingly."""
        prog = [
            {"code": 32, "jt": 0, "jf": 0, "k": 0},
            {"code": 21, "jt": 0, "jf": 1, "k": 0},
            {"code": 6, "jt": 0, "jf": 0, "k": SECCOMP_RET_ALLOW},
            {"code": 6, "jt": 0, "jf": 0, "k": SECCOMP_RET_KILL},
        ]
        assert self.simulate(prog, make_seccomp_data(0)) == SECCOMP_RET_ALLOW
        assert self.simulate(prog, make_seccomp_data(1)) == SECCOMP_RET_KILL
        assert self.simulate(prog, make_seccomp_data(59)) == SECCOMP_RET_KILL

    def test_load_args_low_bits(self):
        """Load the low 32 bits of args[0] at offset 16."""
        prog = [
            {"code": 32, "jt": 0, "jf": 0, "k": 16},
            {"code": 21, "jt": 0, "jf": 1, "k": 42},
            {"code": 6, "jt": 0, "jf": 0, "k": SECCOMP_RET_ALLOW},
            {"code": 6, "jt": 0, "jf": 0, "k": SECCOMP_RET_KILL},
        ]
        assert (
            self.simulate(prog, make_seccomp_data(0, [42, 0, 0, 0, 0, 0]))
            == SECCOMP_RET_ALLOW
        )
        assert (
            self.simulate(prog, make_seccomp_data(0, [43, 0, 0, 0, 0, 0]))
            == SECCOMP_RET_KILL
        )

    def test_load_args_high_bits(self):
        """Load the high 32 bits of args[0] at offset 20."""
        prog = [
            {"code": 32, "jt": 0, "jf": 0, "k": 20},
            {"code": 21, "jt": 0, "jf": 1, "k": 1},
            {"code": 6, "jt": 0, "jf": 0, "k": SECCOMP_RET_ALLOW},
            {"code": 6, "jt": 0, "jf": 0, "k": SECCOMP_RET_KILL},
        ]
        assert (
            self.simulate(
                prog, make_seccomp_data(0, [0x100000000, 0, 0, 0, 0, 0])
            )
            == SECCOMP_RET_ALLOW
        )
        assert (
            self.simulate(prog, make_seccomp_data(0, [42, 0, 0, 0, 0, 0]))
            == SECCOMP_RET_KILL
        )

    def test_alu_and(self):
        """Test ALU AND with immediate."""
        prog = [
            {"code": 32, "jt": 0, "jf": 0, "k": 16},
            {"code": 84, "jt": 0, "jf": 0, "k": 3},
            {"code": 21, "jt": 0, "jf": 1, "k": 1},
            {"code": 6, "jt": 0, "jf": 0, "k": SECCOMP_RET_ALLOW},
            {"code": 6, "jt": 0, "jf": 0, "k": SECCOMP_RET_KILL},
        ]
        assert (
            self.simulate(prog, make_seccomp_data(0, [5, 0, 0, 0, 0, 0]))
            == SECCOMP_RET_ALLOW
        )
        assert (
            self.simulate(prog, make_seccomp_data(0, [6, 0, 0, 0, 0, 0]))
            == SECCOMP_RET_KILL
        )

    def test_jset_bit_test(self):
        """Test JSET (bitwise AND test) opcode."""
        prog = [
            {"code": 32, "jt": 0, "jf": 0, "k": 16},
            {"code": 69, "jt": 1, "jf": 0, "k": 4},
            {"code": 6, "jt": 0, "jf": 0, "k": SECCOMP_RET_ALLOW},
            {"code": 6, "jt": 0, "jf": 0, "k": SECCOMP_RET_KILL},
        ]
        assert (
            self.simulate(prog, make_seccomp_data(0, [3, 0, 0, 0, 0, 0]))
            == SECCOMP_RET_ALLOW
        )
        assert (
            self.simulate(prog, make_seccomp_data(0, [5, 0, 0, 0, 0, 0]))
            == SECCOMP_RET_KILL
        )

    def test_jgt_unsigned(self):
        """Test JGT (unsigned greater than) opcode."""
        prog = [
            {"code": 32, "jt": 0, "jf": 0, "k": 16},
            {"code": 37, "jt": 0, "jf": 1, "k": 10},
            {"code": 6, "jt": 0, "jf": 0, "k": SECCOMP_RET_ALLOW},
            {"code": 6, "jt": 0, "jf": 0, "k": SECCOMP_RET_KILL},
        ]
        assert (
            self.simulate(prog, make_seccomp_data(0, [11, 0, 0, 0, 0, 0]))
            == SECCOMP_RET_ALLOW
        )
        assert (
            self.simulate(prog, make_seccomp_data(0, [10, 0, 0, 0, 0, 0]))
            == SECCOMP_RET_KILL
        )

    def test_jge_unsigned(self):
        """Test JGE (unsigned greater than or equal) opcode."""
        prog = [
            {"code": 32, "jt": 0, "jf": 0, "k": 16},
            {"code": 53, "jt": 0, "jf": 1, "k": 10},
            {"code": 6, "jt": 0, "jf": 0, "k": SECCOMP_RET_ALLOW},
            {"code": 6, "jt": 0, "jf": 0, "k": SECCOMP_RET_KILL},
        ]
        assert (
            self.simulate(prog, make_seccomp_data(0, [10, 0, 0, 0, 0, 0]))
            == SECCOMP_RET_ALLOW
        )
        assert (
            self.simulate(prog, make_seccomp_data(0, [9, 0, 0, 0, 0, 0]))
            == SECCOMP_RET_KILL
        )

    def test_multi_hop_jumps(self):
        """Test a chain of JEQ comparisons with varying jump distances."""
        prog = [
            {"code": 32, "jt": 0, "jf": 0, "k": 0},
            {"code": 21, "jt": 3, "jf": 0, "k": 100},
            {"code": 21, "jt": 2, "jf": 0, "k": 200},
            {"code": 21, "jt": 1, "jf": 0, "k": 300},
            {"code": 6, "jt": 0, "jf": 0, "k": SECCOMP_RET_KILL},
            {"code": 6, "jt": 0, "jf": 0, "k": SECCOMP_RET_ALLOW},
        ]
        assert self.simulate(prog, make_seccomp_data(100)) == SECCOMP_RET_ALLOW
        assert self.simulate(prog, make_seccomp_data(200)) == SECCOMP_RET_ALLOW
        assert self.simulate(prog, make_seccomp_data(300)) == SECCOMP_RET_ALLOW
        assert self.simulate(prog, make_seccomp_data(400)) == SECCOMP_RET_KILL

    def test_load_different_arg_indices(self):
        """Verify correct offset mapping for args[0] through args[5]."""
        for i in range(6):
            offset = 16 + i * 8
            prog = [
                {"code": 32, "jt": 0, "jf": 0, "k": offset},
                {"code": 21, "jt": 0, "jf": 1, "k": 99},
                {"code": 6, "jt": 0, "jf": 0, "k": SECCOMP_RET_ALLOW},
                {"code": 6, "jt": 0, "jf": 0, "k": SECCOMP_RET_KILL},
            ]
            args = [0, 0, 0, 0, 0, 0]
            args[i] = 99
            assert (
                self.simulate(prog, make_seccomp_data(0, args))
                == SECCOMP_RET_ALLOW
            ), f"Failed loading args[{i}] at offset {offset}"


# ============================================================
# Test Suite 2: Decoded Filters Match Binary Files
# ============================================================


class TestDecodedFilters:
    """Verify the agent correctly decoded binary BPF filter files to JSON."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with open("/app/decoded_filters.json") as f:
            self.decoded = json.load(f)

    def test_has_all_filters(self):
        for name in ["stdio_mmap", "network_socket", "fs_readonly"]:
            assert name in self.decoded, f"Missing decoded filter: {name}"

    def test_stdio_mmap_matches_binary(self):
        expected = decode_binary_filter("/app/stdio_mmap.bpf")
        assert self.decoded["stdio_mmap"] == expected

    def test_network_socket_matches_binary(self):
        expected = decode_binary_filter("/app/network_socket.bpf")
        assert self.decoded["network_socket"] == expected

    def test_fs_readonly_matches_binary(self):
        expected = decode_binary_filter("/app/fs_readonly.bpf")
        assert self.decoded["fs_readonly"] == expected


# ============================================================
# Test Suite 3: Buggy Filters Exhibit Expected Bugs
# ============================================================


class TestBuggyBehavior:
    """Confirm the original binary filters have the bugs the agent should find."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.simulate = load_simulator()

    def test_stdio_mmap_bug_allows_prot_exec(self):
        """Buggy filter allows mmap with PROT_EXEC when length lacks bit 2."""
        f = decode_binary_filter("/app/stdio_mmap.bpf")
        data = make_seccomp_data(9, [0, 4096, 5, 0x22, 0, 0])
        result = self.simulate(f, data)
        assert result == SECCOMP_RET_ALLOW, (
            "Buggy stdio_mmap should incorrectly ALLOW mmap with PROT_EXEC"
        )

    def test_network_socket_bug_kills_inet6(self):
        """Buggy filter kills AF_INET6 sockets that should be allowed."""
        f = decode_binary_filter("/app/network_socket.bpf")
        data = make_seccomp_data(41, [10, 1, 0, 0, 0, 0])
        result = self.simulate(f, data)
        assert result == SECCOMP_RET_KILL, (
            "Buggy network_socket should incorrectly KILL AF_INET6 SOCK_STREAM"
        )

    def test_fs_readonly_bug_allows_wronly(self):
        """Buggy filter allows open with O_WRONLY."""
        f = decode_binary_filter("/app/fs_readonly.bpf")
        data = make_seccomp_data(2, [0x7FFF0000, 1, 0, 0, 0, 0])
        result = self.simulate(f, data)
        assert result == SECCOMP_RET_ALLOW, (
            "Buggy fs_readonly should incorrectly ALLOW open with O_WRONLY"
        )


# ============================================================
# Test Suite 4: Fixed Binary Filters Pass Policy Tests
# ============================================================


class TestFixedStdioMmap:
    """Verify the fixed stdio_mmap binary filter matches its intended policy."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.simulate = load_simulator()
        self.f = decode_binary_filter("/app/fixed/stdio_mmap.bpf")

    def test_allows_read(self):
        assert self.simulate(self.f, make_seccomp_data(0)) == SECCOMP_RET_ALLOW

    def test_allows_write(self):
        assert self.simulate(self.f, make_seccomp_data(1)) == SECCOMP_RET_ALLOW

    def test_allows_exit(self):
        assert self.simulate(self.f, make_seccomp_data(60)) == SECCOMP_RET_ALLOW

    def test_allows_exit_group(self):
        assert self.simulate(self.f, make_seccomp_data(231)) == SECCOMP_RET_ALLOW

    def test_allows_brk(self):
        assert self.simulate(self.f, make_seccomp_data(12)) == SECCOMP_RET_ALLOW

    def test_allows_mmap_read_only(self):
        data = make_seccomp_data(9, [0, 4096, 1, 0x22, 0, 0])
        assert self.simulate(self.f, data) == SECCOMP_RET_ALLOW

    def test_allows_mmap_read_write(self):
        data = make_seccomp_data(9, [0, 4096, 3, 0x22, 0, 0])
        assert self.simulate(self.f, data) == SECCOMP_RET_ALLOW

    def test_kills_mmap_with_exec(self):
        data = make_seccomp_data(9, [0, 4096, 5, 0x22, 0, 0])
        assert self.simulate(self.f, data) == SECCOMP_RET_KILL

    def test_kills_mmap_with_rwx(self):
        data = make_seccomp_data(9, [0, 4096, 7, 0x22, 0, 0])
        assert self.simulate(self.f, data) == SECCOMP_RET_KILL

    def test_kills_mmap_exec_only(self):
        data = make_seccomp_data(9, [0, 4096, 4, 0x22, 0, 0])
        assert self.simulate(self.f, data) == SECCOMP_RET_KILL

    def test_kills_open(self):
        assert self.simulate(self.f, make_seccomp_data(2)) == SECCOMP_RET_KILL

    def test_kills_socket(self):
        assert self.simulate(self.f, make_seccomp_data(41)) == SECCOMP_RET_KILL

    def test_kills_execve(self):
        assert self.simulate(self.f, make_seccomp_data(59)) == SECCOMP_RET_KILL

    def test_kills_unknown_syscall(self):
        assert self.simulate(self.f, make_seccomp_data(999)) == SECCOMP_RET_KILL


class TestFixedNetworkSocket:
    """Verify the fixed network_socket binary filter matches its intended policy."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.simulate = load_simulator()
        self.f = decode_binary_filter("/app/fixed/network_socket.bpf")

    def test_allows_read(self):
        assert self.simulate(self.f, make_seccomp_data(0)) == SECCOMP_RET_ALLOW

    def test_allows_write(self):
        assert self.simulate(self.f, make_seccomp_data(1)) == SECCOMP_RET_ALLOW

    def test_allows_close(self):
        assert self.simulate(self.f, make_seccomp_data(3)) == SECCOMP_RET_ALLOW

    def test_allows_connect(self):
        assert self.simulate(self.f, make_seccomp_data(42)) == SECCOMP_RET_ALLOW

    def test_allows_sendto(self):
        assert self.simulate(self.f, make_seccomp_data(44)) == SECCOMP_RET_ALLOW

    def test_allows_recvfrom(self):
        assert self.simulate(self.f, make_seccomp_data(45)) == SECCOMP_RET_ALLOW

    def test_allows_inet_stream(self):
        data = make_seccomp_data(41, [2, 1, 0, 0, 0, 0])
        assert self.simulate(self.f, data) == SECCOMP_RET_ALLOW

    def test_allows_inet_dgram(self):
        data = make_seccomp_data(41, [2, 2, 0, 0, 0, 0])
        assert self.simulate(self.f, data) == SECCOMP_RET_ALLOW

    def test_allows_inet6_stream(self):
        data = make_seccomp_data(41, [10, 1, 0, 0, 0, 0])
        assert self.simulate(self.f, data) == SECCOMP_RET_ALLOW

    def test_allows_inet6_dgram(self):
        data = make_seccomp_data(41, [10, 2, 0, 0, 0, 0])
        assert self.simulate(self.f, data) == SECCOMP_RET_ALLOW

    def test_allows_inet_stream_cloexec(self):
        data = make_seccomp_data(41, [2, 0x80001, 0, 0, 0, 0])
        assert self.simulate(self.f, data) == SECCOMP_RET_ALLOW

    def test_allows_inet_dgram_nonblock(self):
        data = make_seccomp_data(41, [2, 0x802, 0, 0, 0, 0])
        assert self.simulate(self.f, data) == SECCOMP_RET_ALLOW

    def test_allows_inet6_stream_cloexec_nonblock(self):
        data = make_seccomp_data(41, [10, 0x80801, 0, 0, 0, 0])
        assert self.simulate(self.f, data) == SECCOMP_RET_ALLOW

    def test_allows_inet6_dgram_nonblock(self):
        data = make_seccomp_data(41, [10, 0x802, 0, 0, 0, 0])
        assert self.simulate(self.f, data) == SECCOMP_RET_ALLOW

    def test_kills_unix_stream(self):
        data = make_seccomp_data(41, [1, 1, 0, 0, 0, 0])
        assert self.simulate(self.f, data) == SECCOMP_RET_KILL

    def test_kills_inet_raw(self):
        data = make_seccomp_data(41, [2, 3, 0, 0, 0, 0])
        assert self.simulate(self.f, data) == SECCOMP_RET_KILL

    def test_kills_inet6_raw(self):
        data = make_seccomp_data(41, [10, 3, 0, 0, 0, 0])
        assert self.simulate(self.f, data) == SECCOMP_RET_KILL

    def test_kills_netlink(self):
        data = make_seccomp_data(41, [16, 2, 0, 0, 0, 0])
        assert self.simulate(self.f, data) == SECCOMP_RET_KILL

    def test_kills_open(self):
        assert self.simulate(self.f, make_seccomp_data(2)) == SECCOMP_RET_KILL

    def test_kills_execve(self):
        assert self.simulate(self.f, make_seccomp_data(59)) == SECCOMP_RET_KILL

    def test_kills_mmap(self):
        assert self.simulate(self.f, make_seccomp_data(9)) == SECCOMP_RET_KILL


class TestFixedFsReadonly:
    """Verify the fixed fs_readonly binary filter matches its intended policy."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.simulate = load_simulator()
        self.f = decode_binary_filter("/app/fixed/fs_readonly.bpf")

    def test_allows_read(self):
        assert self.simulate(self.f, make_seccomp_data(0)) == SECCOMP_RET_ALLOW

    def test_allows_close(self):
        assert self.simulate(self.f, make_seccomp_data(3)) == SECCOMP_RET_ALLOW

    def test_allows_fstat(self):
        assert self.simulate(self.f, make_seccomp_data(5)) == SECCOMP_RET_ALLOW

    def test_allows_lseek(self):
        assert self.simulate(self.f, make_seccomp_data(8)) == SECCOMP_RET_ALLOW

    def test_allows_exit(self):
        assert self.simulate(self.f, make_seccomp_data(60)) == SECCOMP_RET_ALLOW

    def test_allows_exit_group(self):
        assert self.simulate(self.f, make_seccomp_data(231)) == SECCOMP_RET_ALLOW

    def test_allows_open_rdonly(self):
        data = make_seccomp_data(2, [0x7FFF0000, 0, 0, 0, 0, 0])
        assert self.simulate(self.f, data) == SECCOMP_RET_ALLOW

    def test_allows_open_rdonly_nonblock(self):
        data = make_seccomp_data(2, [0x7FFF0000, 0x800, 0, 0, 0, 0])
        assert self.simulate(self.f, data) == SECCOMP_RET_ALLOW

    def test_kills_open_wronly(self):
        data = make_seccomp_data(2, [0x7FFF0000, 1, 0, 0, 0, 0])
        assert self.simulate(self.f, data) == SECCOMP_RET_KILL

    def test_kills_open_rdwr(self):
        data = make_seccomp_data(2, [0x7FFF0000, 2, 0, 0, 0, 0])
        assert self.simulate(self.f, data) == SECCOMP_RET_KILL

    def test_kills_open_wronly_creat(self):
        data = make_seccomp_data(2, [0x7FFF0000, 0x41, 0, 0, 0, 0])
        assert self.simulate(self.f, data) == SECCOMP_RET_KILL

    def test_kills_open_rdwr_trunc(self):
        data = make_seccomp_data(2, [0x7FFF0000, 0x202, 0, 0, 0, 0])
        assert self.simulate(self.f, data) == SECCOMP_RET_KILL

    def test_kills_socket(self):
        assert self.simulate(self.f, make_seccomp_data(41)) == SECCOMP_RET_KILL

    def test_kills_execve(self):
        assert self.simulate(self.f, make_seccomp_data(59)) == SECCOMP_RET_KILL

    def test_kills_write(self):
        assert self.simulate(self.f, make_seccomp_data(1)) == SECCOMP_RET_KILL

    def test_kills_mmap(self):
        assert self.simulate(self.f, make_seccomp_data(9)) == SECCOMP_RET_KILL


# ============================================================
# Test Suite 5: Audit Report Correctness
# ============================================================


class TestAuditReport:
    """Verify the audit report identifies the correct bugs."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with open("/app/audit.json") as f:
            self.audit = json.load(f)

    def test_has_all_filters(self):
        for name in ["stdio_mmap", "network_socket", "fs_readonly"]:
            assert name in self.audit, f"Missing audit entry for {name}"

    def test_stdio_mmap_buggy_index(self):
        assert self.audit["stdio_mmap"]["buggy_instruction_index"] == 7

    def test_network_socket_buggy_index(self):
        assert self.audit["network_socket"]["buggy_instruction_index"] == 10

    def test_fs_readonly_buggy_index(self):
        assert self.audit["fs_readonly"]["buggy_instruction_index"] == 8

    def test_all_have_descriptions(self):
        for name in ["stdio_mmap", "network_socket", "fs_readonly"]:
            desc = self.audit[name].get("description", "")
            assert len(desc) > 20, (
                f"Audit description for {name} is too short or missing"
            )


# ============================================================
# Test Suite 6: Toolchain and Verification
# ============================================================


class TestToolchain:
    """Verify the C SECCOMP harness compiles and verification was performed."""

    def test_c_harness_compiles(self):
        """The C SECCOMP loader must compile successfully with gcc."""
        result = subprocess.run(
            ["gcc", "-Wall", "-o", "/tmp/test_loader", "/app/seccomp_loader.c"],
            capture_output=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"C harness compilation failed:\n{result.stderr.decode()}"
        )

    def test_verify_output_exists(self):
        """Agent must have produced verification output from C harness testing."""
        assert os.path.exists("/app/verify_output.txt"), (
            "verify_output.txt not found — agent must compile and run the "
            "C SECCOMP harness against the fixed binary filters"
        )
        with open("/app/verify_output.txt") as f:
            content = f.read()
        assert len(content) > 0, "verify_output.txt is empty"

    def test_fixed_binary_files_exist(self):
        """All three fixed binary filter files must exist."""
        for name in ["stdio_mmap", "network_socket", "fs_readonly"]:
            path = f"/app/fixed/{name}.bpf"
            assert os.path.exists(path), f"Missing fixed filter: {path}"

    def test_fixed_binary_valid_format(self):
        """Fixed binary files must have valid sock_filter wire format (8-byte aligned)."""
        for name in ["stdio_mmap", "network_socket", "fs_readonly"]:
            path = f"/app/fixed/{name}.bpf"
            size = os.path.getsize(path)
            assert size > 0, f"{path} is empty"
            assert size % 8 == 0, (
                f"{path} size {size} is not a multiple of 8 (sock_filter struct size)"
            )
