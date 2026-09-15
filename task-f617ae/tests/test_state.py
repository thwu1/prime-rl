
import subprocess
import os
import json
import struct
import math
import pytest

COMPILER = "/app/compiler.py"
OUTPUT = "/app/output.bc"
VM_RUNNER = "/app/vm_runner"
TEST_VECTORS = "/app/test_vectors.json"

M = 0xFFFFFFFF
MAGIC  = [0xA5B4C3D2, 0x1F2E3D4C, 0x9A8B7C6D, 0x5E4F3A2B, 0xD1C2B3A4]
PRIMES = [0x01000193, 0x811C9DC5, 0xC4CEB9FE, 0x13375EED, 0xDEADC0DE]
ROUND2 = [0x85EBCA6B, 0xC2B2AE35, 0x7FEB352D, 0x846CA68B, 0x9E3779B9]

# Hidden test seeds not present in test_vectors.json
HIDDEN_SEEDS = [0x77777777, 0xABCD1234, 0x99887766, 0x11223344, 0x55AA55AA]

# Instruction sizes for bytecode parsing
INSN_SIZES = {
    0x00: 1, 0x01: 5, 0x02: 2, 0x03: 2, 0x04: 2,
    0x05: 1, 0x06: 1, 0x07: 1, 0x08: 1, 0x09: 1,
    0x0A: 1, 0x0B: 1, 0x0C: 1, 0x0D: 1, 0x0E: 1,
    0x0F: 1, 0x10: 1, 0x11: 1, 0x12: 1, 0x13: 1,
    0x14: 1, 0x15: 3, 0x16: 3, 0x17: 3, 0x18: 2,
    0x19: 1, 0x1A: 1,
}


def compute_groups(seed):
    """Forward-compute valid key groups for a given seed."""
    groups = []
    s = seed
    for i in range(5):
        val = s
        val = ((val ^ MAGIC[i]) * PRIMES[i]) & M
        val = ((val >> 13) | (val << 19)) & M
        val = (val ^ (val >> 16)) & M
        val = ((val + ROUND2[i]) & M) ^ s
        val = val & M
        val = ((val << 7) | (val >> 25)) & M
        val = (val * 0x5BD1E995) & M
        val = (val ^ (val >> 15)) & M
        groups.append(val)
        s = ((s ^ val) + MAGIC[i]) & M
        s = ((s >> 11) | (s << 21)) & M
        s = (s * 0x1B873593) & M
    return groups


def parse_bytecode(bc):
    """Parse bytecode into list of (pc, opcode, size). Returns None if invalid."""
    instructions = []
    pc = 0
    while pc < len(bc):
        op = bc[pc]
        size = INSN_SIZES.get(op)
        if size is None:
            return None
        if pc + size > len(bc):
            return None
        instructions.append((pc, op, size))
        pc += size
    return instructions


def shannon_entropy(data):
    """Compute Shannon entropy in bits per byte."""
    if not data:
        return 0.0
    freq = [0] * 256
    for b in data:
        freq[b] += 1
    n = len(data)
    entropy = 0.0
    for f in freq:
        if f > 0:
            p = f / n
            entropy -= p * math.log2(p)
    return entropy


class TracingVM:
    """Python VM simulator with execution tracing for security analysis."""

    def __init__(self, bc):
        self.bc = bc
        self.mem = [0] * 32
        self.stack = []
        self.visited_pcs = set()
        self.branch_outcomes = {}

    def run(self, mem_init):
        self.mem = [0] * 32
        for i, v in enumerate(mem_init):
            self.mem[i] = v & M
        self.stack = []
        pc = 0
        halted = False
        result = 1
        steps = 0
        max_steps = 5000000

        while not halted and pc < len(self.bc) and steps < max_steps:
            steps += 1
            insn_pc = pc
            self.visited_pcs.add(pc)
            op = self.bc[pc]
            pc += 1

            if op == 0x00:
                pass
            elif op == 0x01:
                imm = struct.unpack_from('<I', self.bc, pc)[0]
                pc += 4
                self.stack.append(imm)
            elif op == 0x02:
                self.stack.append(self.bc[pc])
                pc += 1
            elif op == 0x03:
                addr = self.bc[pc] & 0x1F
                pc += 1
                self.stack.append(self.mem[addr])
            elif op == 0x04:
                addr = self.bc[pc] & 0x1F
                pc += 1
                self.mem[addr] = self.stack.pop() & M
            elif op == 0x05:
                self.stack.append(self.stack[-1])
            elif op == 0x06:
                self.stack.pop()
            elif op == 0x07:
                self.stack[-1], self.stack[-2] = self.stack[-2], self.stack[-1]
            elif op == 0x08:
                a = self.stack.pop()
                self.stack[-1] = (self.stack[-1] + a) & M
            elif op == 0x09:
                a = self.stack.pop()
                self.stack[-1] = (self.stack[-1] - a) & M
            elif op == 0x0A:
                a = self.stack.pop()
                self.stack[-1] = (self.stack[-1] * a) & M
            elif op == 0x0B:
                a = self.stack.pop()
                self.stack[-1] = (self.stack[-1] ^ a) & M
            elif op == 0x0C:
                a = self.stack.pop()
                self.stack[-1] = (self.stack[-1] & a) & M
            elif op == 0x0D:
                a = self.stack.pop()
                self.stack[-1] = (self.stack[-1] | a) & M
            elif op == 0x0E:
                a = self.stack.pop() & 31
                self.stack[-1] = (self.stack[-1] >> a) & M
            elif op == 0x0F:
                a = self.stack.pop() & 31
                self.stack[-1] = (self.stack[-1] << a) & M
            elif op == 0x10:
                a = self.stack.pop() & 31
                b = self.stack[-1]
                self.stack[-1] = ((b >> a) | (b << (32 - a))) & M if a else b
            elif op == 0x11:
                a = self.stack.pop() & 31
                b = self.stack[-1]
                self.stack[-1] = ((b << a) | (b >> (32 - a))) & M if a else b
            elif op == 0x12:
                a = self.stack.pop()
                if a:
                    self.stack[-1] = self.stack[-1] % a
            elif op == 0x13:
                a = self.stack.pop()
                b = self.stack.pop()
                self.stack.append(1 if b == a else 0)
            elif op == 0x14:
                a = self.stack.pop()
                b = self.stack.pop()
                self.stack.append(1 if b != a else 0)
            elif op == 0x15:
                target = struct.unpack_from('<H', self.bc, pc)[0]
                pc = target
            elif op == 0x16:
                target = struct.unpack_from('<H', self.bc, pc)[0]
                pc += 2
                val = self.stack.pop()
                taken = val == 0
                if insn_pc not in self.branch_outcomes:
                    self.branch_outcomes[insn_pc] = set()
                self.branch_outcomes[insn_pc].add(taken)
                if taken:
                    pc = target
            elif op == 0x17:
                target = struct.unpack_from('<H', self.bc, pc)[0]
                pc += 2
                val = self.stack.pop()
                taken = val != 0
                if insn_pc not in self.branch_outcomes:
                    self.branch_outcomes[insn_pc] = set()
                self.branch_outcomes[insn_pc].add(taken)
                if taken:
                    pc = target
            elif op == 0x18:
                result = self.bc[pc]
                pc += 1
                halted = True
            elif op == 0x19:
                self.stack[-1] = (~self.stack[-1]) & M
            elif op == 0x1A:
                self.stack.append(self.stack[-2])
            else:
                halted = True
                result = 1

        return result


def build_all_mem_inits(test_vectors):
    """Build mem init lists from public + hidden test vectors."""
    all_inits = []
    for tv in test_vectors:
        seed = int(tv["seed"], 16)
        groups = [int(g, 16) for g in tv["groups"]]
        all_inits.append([seed] + groups)
    # Hidden valid
    for seed in HIDDEN_SEEDS:
        groups = compute_groups(seed)
        all_inits.append([seed] + groups)
    # Hidden invalid — corrupt group idx to cover all 5 groups
    for idx, seed in enumerate(HIDDEN_SEEDS):
        groups = compute_groups(seed)
        groups[idx % 5] ^= 0x01
        all_inits.append([seed] + groups)
    return all_inits


@pytest.fixture(scope="session")
def compiled_bytecode():
    """Run the compiler and return the bytecode."""
    assert os.path.exists(COMPILER), f"Compiler not found at {COMPILER}"
    result = subprocess.run(
        ["python3", COMPILER],
        capture_output=True, text=True, timeout=60, cwd="/app",
    )
    assert result.returncode == 0, f"Compiler failed: {result.stderr}"
    assert os.path.exists(OUTPUT), f"Output bytecode not found at {OUTPUT}"
    with open(OUTPUT, "rb") as f:
        bc = f.read()
    assert len(bc) > 0, "Output bytecode is empty"
    assert len(bc) <= 16384, f"Bytecode too large: {len(bc)} bytes (max 16384)"
    return bc


@pytest.fixture(scope="session")
def test_vectors():
    with open(TEST_VECTORS) as f:
        return json.load(f)


# ===== Functional Correctness =====

class TestFunctionalCorrectness:

    def test_valid_accept(self, compiled_bytecode, test_vectors):
        """All valid test vectors must be accepted."""
        valid = [v for v in test_vectors if v["expected"] == 0]
        assert len(valid) >= 10
        for tv in valid:
            args = [VM_RUNNER, OUTPUT, tv["seed"]] + tv["groups"]
            r = subprocess.run(args, capture_output=True, text=True, timeout=10)
            assert r.returncode == 0, (
                f"Valid key rejected for seed={tv['seed']}: {r.stdout.strip()}"
            )

    def test_invalid_reject(self, compiled_bytecode, test_vectors):
        """All invalid test vectors must be rejected."""
        invalid = [v for v in test_vectors if v["expected"] == 1]
        assert len(invalid) >= 5
        for tv in invalid:
            args = [VM_RUNNER, OUTPUT, tv["seed"]] + tv["groups"]
            r = subprocess.run(args, capture_output=True, text=True, timeout=10)
            assert r.returncode != 0, (
                f"Invalid key accepted for seed={tv['seed']}"
            )

    def test_hidden_valid(self, compiled_bytecode):
        """Seeds not in test_vectors.json must also be handled correctly."""
        for seed in HIDDEN_SEEDS:
            groups = compute_groups(seed)
            args = [VM_RUNNER, OUTPUT, f"{seed:08X}"] + [f"{g:08X}" for g in groups]
            r = subprocess.run(args, capture_output=True, text=True, timeout=10)
            assert r.returncode == 0, (
                f"Hidden valid key rejected for seed={seed:#010x}"
            )

    def test_hidden_invalid(self, compiled_bytecode):
        """Corrupted hidden keys must be rejected (covers all 5 group indices)."""
        for idx, seed in enumerate(HIDDEN_SEEDS):
            groups = compute_groups(seed)
            groups[idx % 5] ^= 0x01
            args = [VM_RUNNER, OUTPUT, f"{seed:08X}"] + [f"{g:08X}" for g in groups]
            r = subprocess.run(args, capture_output=True, text=True, timeout=10)
            assert r.returncode != 0, (
                f"Hidden invalid key accepted for seed={seed:#010x} "
                f"(corrupted group {idx % 5})"
            )


# ===== Bytecode Validity =====

class TestBytecodeValidity:

    def test_parseable(self, compiled_bytecode):
        """Bytecode must consist entirely of valid instruction sequences."""
        instructions = parse_bytecode(compiled_bytecode)
        assert instructions is not None, (
            "Bytecode contains invalid opcodes or truncated instructions"
        )
        assert len(instructions) > 0, "Bytecode has no instructions"


# ===== Security Metrics =====

class TestSecurityMetrics:

    def test_entropy(self, compiled_bytecode):
        """Shannon entropy must be >= 4.5 bits/byte."""
        ent = shannon_entropy(compiled_bytecode)
        assert ent >= 4.5, (
            f"Entropy too low: {ent:.2f} bits/byte (minimum 4.5)"
        )

    def test_instruction_count(self, compiled_bytecode):
        """Must have >= 500 instructions."""
        instructions = parse_bytecode(compiled_bytecode)
        assert instructions is not None
        count = len(instructions)
        assert count >= 500, (
            f"Instruction count too low: {count} (minimum 500)"
        )

    def test_dead_code(self, compiled_bytecode, test_vectors):
        """At least 15% of instructions must be dead code."""
        instructions = parse_bytecode(compiled_bytecode)
        assert instructions is not None
        all_pcs = {pc for pc, _, _ in instructions}

        visited = set()
        for mem_init in build_all_mem_inits(test_vectors):
            vm = TracingVM(compiled_bytecode)
            vm.run(mem_init)
            visited |= vm.visited_pcs

        dead_pcs = all_pcs - visited
        dead_ratio = len(dead_pcs) / len(all_pcs) if all_pcs else 0
        assert dead_ratio >= 0.15, (
            f"Dead code ratio too low: {dead_ratio:.2%} "
            f"({len(dead_pcs)}/{len(all_pcs)}) — minimum 15%"
        )

    def test_opaque_predicates(self, compiled_bytecode, test_vectors):
        """At least 5 conditional jumps must be opaque predicates."""
        branch_outcomes = {}
        for mem_init in build_all_mem_inits(test_vectors):
            vm = TracingVM(compiled_bytecode)
            vm.run(mem_init)
            for pc, outcomes in vm.branch_outcomes.items():
                if pc not in branch_outcomes:
                    branch_outcomes[pc] = set()
                branch_outcomes[pc] |= outcomes

        opaque_count = sum(
            1 for outcomes in branch_outcomes.values()
            if len(outcomes) == 1
        )
        assert opaque_count >= 5, (
            f"Too few opaque predicates: {opaque_count} (minimum 5). "
            f"Total conditional branches: {len(branch_outcomes)}"
        )
