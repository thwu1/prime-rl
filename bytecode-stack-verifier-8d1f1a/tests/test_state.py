"""
Bytecode toolchain test suite.

Tests verify that the disassembler, optimizer, and verifier correctly
process BCVF bytecode programs, individually and as a pipeline.

"""

import struct
import subprocess
import tempfile
import os
import pytest

OPTIMIZER = "/app/src/optimizer"
VERIFIER = "/app/src/verifier"
BCDUMP = "/app/src/bcdump"

# ===================================================================
# Opcode constants — must match the enum order in opcode_def.h
# ===================================================================
OP_invalid       = 0
OP_push_i32      = 1
OP_push_const    = 2
OP_undefined     = 3
OP_null_val      = 4
OP_push_false    = 5
OP_push_true     = 6
OP_object        = 7
OP_drop          = 8
OP_dup           = 9
OP_dup2          = 10
OP_swap          = 11
OP_rot3l         = 12
OP_add           = 13
OP_sub           = 14
OP_mul           = 15
OP_div_op        = 16
OP_mod_op        = 17
OP_neg           = 18
OP_inc           = 19
OP_dec           = 20
OP_shl           = 21
OP_sar           = 22
OP_shr           = 23
OP_bit_and       = 24
OP_bit_or        = 25
OP_bit_xor       = 26
OP_bit_not       = 27
OP_lnot          = 28
OP_eq            = 29
OP_neq           = 30
OP_strict_eq     = 31
OP_strict_neq    = 32
OP_lt            = 33
OP_lte           = 34
OP_gt            = 35
OP_gte           = 36
OP_get_loc       = 37
OP_put_loc       = 38
OP_set_loc       = 39
OP_get_arg       = 40
OP_put_arg       = 41
OP_get_field     = 42
OP_put_field     = 43
OP_get_array_el  = 44
OP_put_array_el  = 45
OP_call          = 46
OP_return_val    = 47
OP_return_undef  = 48
OP_if_false      = 49
OP_if_true       = 50
OP_goto_op       = 51
OP_catch         = 52
OP_end_catch     = 53
OP_throw_op      = 54
OP_typeof_op     = 55
OP_instanceof_op = 56
OP_in_op         = 57
OP_nop           = 58

# Opcode sizes
OPCODE_SIZE = {
    OP_invalid: 1, OP_push_i32: 5, OP_push_const: 5, OP_undefined: 1,
    OP_null_val: 1, OP_push_false: 1, OP_push_true: 1, OP_object: 1,
    OP_drop: 1, OP_dup: 1, OP_dup2: 1, OP_swap: 1, OP_rot3l: 1,
    OP_add: 1, OP_sub: 1, OP_mul: 1, OP_div_op: 1, OP_mod_op: 1,
    OP_neg: 1, OP_inc: 1, OP_dec: 1,
    OP_shl: 1, OP_sar: 1, OP_shr: 1,
    OP_bit_and: 1, OP_bit_or: 1, OP_bit_xor: 1, OP_bit_not: 1, OP_lnot: 1,
    OP_eq: 1, OP_neq: 1, OP_strict_eq: 1, OP_strict_neq: 1,
    OP_lt: 1, OP_lte: 1, OP_gt: 1, OP_gte: 1,
    OP_get_loc: 3, OP_put_loc: 3, OP_set_loc: 3,
    OP_get_arg: 3, OP_put_arg: 3,
    OP_get_field: 5, OP_put_field: 5,
    OP_get_array_el: 1, OP_put_array_el: 1,
    OP_call: 3, OP_return_val: 1, OP_return_undef: 1,
    OP_if_false: 5, OP_if_true: 5, OP_goto_op: 5,
    OP_catch: 5, OP_end_catch: 1, OP_throw_op: 1,
    OP_typeof_op: 1, OP_instanceof_op: 1, OP_in_op: 1,
    OP_nop: 1,
}


# ===================================================================
# Bytecode assembler
# ===================================================================

class BytecodeBuilder:
    """Assembles bytecode programs for the stack VM."""

    def __init__(self, num_locals=0, num_args=0):
        self.code = bytearray()
        self.num_locals = num_locals
        self.num_args = num_args
        self._labels: dict[str, int] = {}
        self._fixups: list[tuple[int, str, int]] = []

    def _pc(self) -> int:
        return len(self.code)

    def label(self, name: str):
        self._labels[name] = self._pc()

    def push_i32(self, val: int):
        self.code.append(OP_push_i32)
        self.code.extend(struct.pack("<i", val))

    def push_true(self):
        self.code.append(OP_push_true)

    def push_false(self):
        self.code.append(OP_push_false)

    def undefined(self):
        self.code.append(OP_undefined)

    def null_val(self):
        self.code.append(OP_null_val)

    def object(self):
        self.code.append(OP_object)

    def drop(self):
        self.code.append(OP_drop)

    def dup(self):
        self.code.append(OP_dup)

    def swap(self):
        self.code.append(OP_swap)

    def add(self):
        self.code.append(OP_add)

    def sub(self):
        self.code.append(OP_sub)

    def mul(self):
        self.code.append(OP_mul)

    def neg(self):
        self.code.append(OP_neg)

    def inc(self):
        self.code.append(OP_inc)

    def dec(self):
        self.code.append(OP_dec)

    def lt(self):
        self.code.append(OP_lt)

    def eq(self):
        self.code.append(OP_eq)

    def get_loc(self, idx: int):
        self.code.append(OP_get_loc)
        self.code.extend(struct.pack("<H", idx))

    def put_loc(self, idx: int):
        self.code.append(OP_put_loc)
        self.code.extend(struct.pack("<H", idx))

    def set_loc(self, idx: int):
        self.code.append(OP_set_loc)
        self.code.extend(struct.pack("<H", idx))

    def get_arg(self, idx: int):
        self.code.append(OP_get_arg)
        self.code.extend(struct.pack("<H", idx))

    def put_arg(self, idx: int):
        self.code.append(OP_put_arg)
        self.code.extend(struct.pack("<H", idx))

    def call(self, argc: int):
        self.code.append(OP_call)
        self.code.extend(struct.pack("<H", argc))

    def return_val(self):
        self.code.append(OP_return_val)

    def return_undef(self):
        self.code.append(OP_return_undef)

    def if_false(self, label_name: str):
        insn_start = self._pc()
        self.code.append(OP_if_false)
        fixup_pos = self._pc()
        self.code.extend(b"\x00\x00\x00\x00")
        self._fixups.append((fixup_pos, label_name, insn_start))

    def if_true(self, label_name: str):
        insn_start = self._pc()
        self.code.append(OP_if_true)
        fixup_pos = self._pc()
        self.code.extend(b"\x00\x00\x00\x00")
        self._fixups.append((fixup_pos, label_name, insn_start))

    def goto(self, label_name: str):
        insn_start = self._pc()
        self.code.append(OP_goto_op)
        fixup_pos = self._pc()
        self.code.extend(b"\x00\x00\x00\x00")
        self._fixups.append((fixup_pos, label_name, insn_start))

    def catch(self, label_name: str):
        insn_start = self._pc()
        self.code.append(OP_catch)
        fixup_pos = self._pc()
        self.code.extend(b"\x00\x00\x00\x00")
        self._fixups.append((fixup_pos, label_name, insn_start))

    def end_catch(self):
        self.code.append(OP_end_catch)

    def throw_op(self):
        self.code.append(OP_throw_op)

    def nop(self):
        self.code.append(OP_nop)

    def build(self) -> bytes:
        code = bytearray(self.code)
        for fixup_pos, label_name, insn_start in self._fixups:
            if label_name not in self._labels:
                raise ValueError(f"undefined label: {label_name}")
            target = self._labels[label_name]
            rel = target - insn_start
            struct.pack_into("<i", code, fixup_pos, rel)
        header = struct.pack(
            "<4sHHI", b"BCVF", self.num_locals, self.num_args, len(code)
        )
        return bytes(header) + bytes(code)


# ===================================================================
# Helpers
# ===================================================================

def get_code_len(bcvf_data: bytes) -> int:
    return struct.unpack_from("<I", bcvf_data, 8)[0]


def parse_instructions(bcvf_data: bytes) -> list:
    """Parse BCVF output into list of (opcode, raw_bytes) tuples."""
    code_len = get_code_len(bcvf_data)
    code = bcvf_data[12:12 + code_len]
    insns = []
    pc = 0
    while pc < len(code):
        op = code[pc]
        sz = OPCODE_SIZE.get(op, 1)
        insns.append((op, bytes(code[pc:pc + sz])))
        pc += sz
    return insns


def get_i32_operand(raw: bytes) -> int:
    """Extract i32 operand from raw instruction bytes."""
    return struct.unpack_from("<i", raw, 1)[0]


def run_optimizer(input_data: bytes) -> bytes:
    """Write input, run optimizer, return output bytes."""
    fd_in, path_in = tempfile.mkstemp(suffix=".bc")
    path_out = path_in + ".opt"
    try:
        os.write(fd_in, input_data)
        os.close(fd_in)
        result = subprocess.run(
            [OPTIMIZER, path_in, path_out],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"optimizer failed: {result.stderr}"
        with open(path_out, "rb") as f:
            return f.read()
    finally:
        if os.path.exists(path_in):
            os.unlink(path_in)
        if os.path.exists(path_out):
            os.unlink(path_out)


def run_verifier(bytecode_data: bytes) -> dict:
    """Run verifier on bytecode, return parsed result dict."""
    fd, path = tempfile.mkstemp(suffix=".bc")
    try:
        os.write(fd, bytecode_data)
        os.close(fd)
        result = subprocess.run(
            [VERIFIER, path], capture_output=True, text=True, timeout=10,
        )
    finally:
        os.unlink(path)
    return _parse_verifier(result.stdout)


def _parse_verifier(stdout: str) -> dict:
    lines = stdout.strip().split("\n") if stdout.strip() else []
    info: dict = {"valid": None, "max_stack": None, "depths": {}, "errors": []}
    for line in lines:
        line = line.strip()
        if line.startswith("RESULT: "):
            info["valid"] = line == "RESULT: VALID"
        elif line.startswith("MAX_STACK: "):
            info["max_stack"] = int(line.split(": ", 1)[1])
        elif line.startswith("DEPTH["):
            bracket_end = line.index("]")
            offset = int(line[6:bracket_end])
            depth = int(line[bracket_end + 3:])
            info["depths"][offset] = depth
        elif line.startswith("ERROR: "):
            info["errors"].append(line[7:])
    return info


def run_bcdump(bytecode_data: bytes) -> str:
    """Run bcdump on bytecode, return stdout."""
    fd, path = tempfile.mkstemp(suffix=".bc")
    try:
        os.write(fd, bytecode_data)
        os.close(fd)
        result = subprocess.run(
            [BCDUMP, path], capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"bcdump failed: {result.stderr}"
        return result.stdout
    finally:
        os.unlink(path)


def parse_bcdump(stdout: str) -> list:
    """Parse bcdump output into list of instruction dicts."""
    insns = []
    for line in stdout.strip().split("\n"):
        line = line.strip()
        if line.startswith(";") or not line:
            continue
        parts = line.split(":", 1)
        if len(parts) != 2:
            continue
        offset = int(parts[0].strip())
        rest = parts[1].strip()
        tokens = rest.split()
        name = tokens[0]
        operand = None
        target = None
        if len(tokens) >= 2 and tokens[1] != "->":
            operand = int(tokens[1])
        if "->" in tokens:
            arrow_idx = tokens.index("->")
            if arrow_idx + 1 < len(tokens):
                target = int(tokens[arrow_idx + 1])
        insns.append({
            "offset": offset,
            "name": name,
            "operand": operand,
            "target": target,
        })
    return insns


def optimize_and_verify(builder_or_data):
    """Build (if builder), optimize, verify. Return (output, verifier_result, insns)."""
    if isinstance(builder_or_data, BytecodeBuilder):
        data = builder_or_data.build()
    else:
        data = builder_or_data
    output = run_optimizer(data)
    vr = run_verifier(output)
    insns = parse_instructions(output)
    return output, vr, insns


# ===================================================================
# Tests — disassembler correctness
# ===================================================================

class TestBcdump:
    """Verify bcdump correctly disassembles BCVF bytecode files."""

    def test_basic_disassembly(self):
        """bcdump produces correct output for a simple program."""
        b = BytecodeBuilder()
        b.push_i32(42)
        b.return_val()
        data = b.build()
        output = run_bcdump(data)
        insns = parse_bcdump(output)
        assert len(insns) == 2
        assert insns[0]["offset"] == 0
        assert insns[0]["name"] == "push_i32"
        assert insns[0]["operand"] == 42
        assert insns[1]["offset"] == 5
        assert insns[1]["name"] == "return_val"

    def test_u16_operand_decoding(self):
        """bcdump correctly decodes u16 operands (little-endian)."""
        b = BytecodeBuilder(num_locals=2)
        b.get_loc(1)          # u16 operand = 1
        b.put_loc(0)          # u16 operand = 0
        b.return_undef()
        data = b.build()
        output = run_bcdump(data)
        insns = parse_bcdump(output)
        assert insns[0]["name"] == "get_loc"
        assert insns[0]["operand"] == 1
        assert insns[1]["name"] == "put_loc"
        assert insns[1]["operand"] == 0

    def test_call_operand(self):
        """bcdump correctly decodes call u16 arg count."""
        b = BytecodeBuilder(num_locals=1)
        b.get_loc(0)          # callee
        b.get_loc(0)          # arg 0
        b.get_loc(0)          # arg 1
        b.call(2)              # u16 operand = 2
        b.return_val()
        data = b.build()
        output = run_bcdump(data)
        insns = parse_bcdump(output)
        call_insn = [i for i in insns if i["name"] == "call"][0]
        assert call_insn["operand"] == 2

    def test_branch_target_resolution(self):
        """bcdump resolves branch targets to absolute addresses."""
        b = BytecodeBuilder()
        b.push_i32(0)         # offset 0, size 5
        b.push_true()          # offset 5, size 1
        b.if_false("L")        # offset 6, size 5; target should be 11
        b.label("L")
        b.return_undef()       # offset 11, size 1
        data = b.build()
        output = run_bcdump(data)
        insns = parse_bcdump(output)
        if_insn = [i for i in insns if i["name"] == "if_false"][0]
        assert if_insn["offset"] == 6
        assert if_insn["target"] == 11

    def test_goto_target_nonzero_offset(self):
        """bcdump resolves goto target when goto is not at offset 0."""
        b = BytecodeBuilder()
        b.push_i32(0)          # offset 0, size 5
        b.goto("L")            # offset 5, size 5; target at 10
        b.label("L")
        b.return_undef()       # offset 10, size 1
        data = b.build()
        output = run_bcdump(data)
        insns = parse_bcdump(output)
        goto_insn = [i for i in insns if i["name"] == "goto_op"][0]
        assert goto_insn["offset"] == 5
        assert goto_insn["target"] == 10

    def test_catch_target_nonzero_offset(self):
        """bcdump resolves catch handler target at non-zero instruction."""
        b = BytecodeBuilder()
        b.push_i32(1)          # offset 0, size 5
        b.catch("H")           # offset 5, size 5; handler at 17
        b.push_i32(2)          # offset 10, size 5
        b.end_catch()          # offset 15, size 1
        b.return_val()         # offset 16, size 1
        b.label("H")
        b.return_val()         # offset 17, size 1
        data = b.build()
        output = run_bcdump(data)
        insns = parse_bcdump(output)
        catch_insn = [i for i in insns if i["name"] == "catch"][0]
        assert catch_insn["offset"] == 5
        assert catch_insn["target"] == 17

    def test_backward_branch(self):
        """bcdump resolves backward branch targets."""
        b = BytecodeBuilder()
        b.label("TOP")
        b.return_undef()       # offset 0, size 1
        b.goto("TOP")          # offset 1, size 5; target = 0
        data = b.build()
        output = run_bcdump(data)
        insns = parse_bcdump(output)
        goto_insn = [i for i in insns if i["name"] == "goto_op"][0]
        assert goto_insn["offset"] == 1
        assert goto_insn["target"] == 0

    def test_negative_operand(self):
        """bcdump correctly prints negative i32 operand."""
        b = BytecodeBuilder()
        b.push_i32(-100)
        b.return_val()
        data = b.build()
        output = run_bcdump(data)
        insns = parse_bcdump(output)
        assert insns[0]["operand"] == -100

    def test_summary_line(self):
        """bcdump prints correct summary."""
        b = BytecodeBuilder()
        b.push_i32(42)
        b.return_val()
        data = b.build()
        output = run_bcdump(data)
        assert "; SUMMARY instructions=2 code_bytes=6" in output

    def test_set_loc_operand(self):
        """bcdump correctly decodes set_loc u16 operand."""
        b = BytecodeBuilder(num_locals=3)
        b.push_i32(1)
        b.set_loc(2)
        b.return_val()
        data = b.build()
        output = run_bcdump(data)
        insns = parse_bcdump(output)
        set_insn = [i for i in insns if i["name"] == "set_loc"][0]
        assert set_insn["operand"] == 2

    def test_get_arg_operand(self):
        """bcdump correctly decodes get_arg u16 operand."""
        b = BytecodeBuilder(num_locals=0, num_args=3)
        b.get_arg(2)
        b.return_val()
        data = b.build()
        output = run_bcdump(data)
        insns = parse_bcdump(output)
        assert insns[0]["name"] == "get_arg"
        assert insns[0]["operand"] == 2


# ===================================================================
# Tests — disassembler + optimizer pipeline
# ===================================================================

class TestBcdumpPipeline:
    """Verify bcdump correctly disassembles optimizer output."""

    def test_fold_verified_by_dump(self):
        """Constant fold result verified via bcdump disassembly."""
        b = BytecodeBuilder()
        b.push_i32(3)
        b.push_i32(4)
        b.add()
        b.return_val()
        output = run_optimizer(b.build())
        dump_output = run_bcdump(output)
        insns = parse_bcdump(dump_output)
        assert len(insns) == 2
        assert insns[0]["name"] == "push_i32"
        assert insns[0]["operand"] == 7
        assert insns[1]["name"] == "return_val"

    def test_goto_threading_verified_by_dump(self):
        """After goto threading, bcdump shows correct direct target."""
        b = BytecodeBuilder(num_locals=1)
        b.get_loc(0)           # 0: 3 bytes (non-optimizable padding)
        b.put_loc(0)           # 3: 3 bytes
        b.goto("L1")           # 6: 5 bytes
        b.label("L1")
        b.goto("L2")           # 11: 5 bytes (threading target, becomes dead)
        b.label("L2")
        b.return_undef()       # 16: 1 byte
        output = run_optimizer(b.build())
        dump_output = run_bcdump(output)
        insns = parse_bcdump(dump_output)
        goto_insn = [i for i in insns if i["name"] == "goto_op"][0]
        ret_insn = [i for i in insns if i["name"] == "return_undef"][0]
        assert goto_insn["target"] == ret_insn["offset"]

    def test_dead_branch_dump_shows_goto(self):
        """After dead branch elimination, bcdump shows converted goto."""
        b = BytecodeBuilder(num_locals=1)
        b.get_loc(0)           # 0: 3 bytes
        b.put_loc(0)           # 3: 3 bytes
        b.push_false()          # 6: 1 byte
        b.if_false("L")        # 7: 5 bytes -> becomes goto L
        b.push_i32(1)          # 12: dead
        b.return_val()         # 17: dead
        b.label("L")
        b.push_i32(2)          # 18: 5 bytes
        b.return_val()         # 23: 1 byte
        output = run_optimizer(b.build())
        dump_output = run_bcdump(output)
        insns = parse_bcdump(dump_output)
        goto_insn = [i for i in insns if i["name"] == "goto_op"][0]
        push2_insn = [i for i in insns if i["name"] == "push_i32"][0]
        assert goto_insn["target"] == push2_insn["offset"]
        assert push2_insn["operand"] == 2


# ===================================================================
# Tests — verifier correctness
# ===================================================================

class TestVerifierCorrectness:
    """Verify the verifier correctly implements the opcode specification."""

    def test_set_loc_preserves_value(self):
        """set_loc keeps value on stack (pop 1, push 1 per spec)."""
        b = BytecodeBuilder(num_locals=1)
        b.get_loc(0)         # 0->1
        b.set_loc(0)          # 1->1 (set_loc preserves value)
        b.return_val()        # 1->0
        input_data = b.build()
        output, vr, _ = optimize_and_verify(input_data)
        assert vr["valid"] is True, f"verifier errors: {vr['errors']}"
        assert vr["max_stack"] == 1

    def test_call_pops_callee_and_args(self):
        """call(N) pops N+1 values (callee + N args), pushes 1."""
        b = BytecodeBuilder(num_locals=1)
        b.get_loc(0)          # callee: 0->1
        b.call(0)              # pop 1, push 1: 1->1
        b.put_loc(0)           # 1->0
        b.return_undef()       # 0->0
        input_data = b.build()
        output, vr, _ = optimize_and_verify(input_data)
        assert vr["valid"] is True, f"verifier errors: {vr['errors']}"
        assert vr["max_stack"] == 1

    def test_conditional_both_paths(self):
        """Both paths of a conditional branch must be depth-tracked."""
        b = BytecodeBuilder(num_locals=1)
        b.get_loc(0)          # 0->1
        b.if_false("L")        # 1->0
        # fall-through: depth 0
        b.get_loc(0)           # 0->1
        b.get_loc(0)           # 1->2
        b.get_loc(0)           # 2->3  <- max only via fall-through
        b.add()                # 3->2
        b.add()                # 2->1
        b.return_val()         # 1->0
        b.label("L")
        b.get_loc(0)           # 0->1
        b.return_val()         # 1->0
        input_data = b.build()
        output, vr, _ = optimize_and_verify(input_data)
        assert vr["valid"] is True, f"verifier errors: {vr['errors']}"
        assert vr["max_stack"] == 3

    def test_goto_propagates_depth(self):
        """goto must propagate stack depth to its target."""
        b = BytecodeBuilder(num_locals=1)
        b.goto("L")
        b.label("L")
        b.get_loc(0)       # 0->1
        b.get_loc(0)       # 1->2
        b.add()             # 2->1
        b.return_val()      # 1->0
        input_data = b.build()
        output, vr, _ = optimize_and_verify(input_data)
        assert vr["valid"] is True, f"verifier errors: {vr['errors']}"
        assert vr["max_stack"] == 2


# ===================================================================
# Tests — identity transform (no optimization opportunities)
# ===================================================================

class TestIdentityTransform:
    def test_simple_return(self):
        """No foldable patterns: output should be identical size."""
        b = BytecodeBuilder()
        b.push_i32(42)
        b.return_val()
        input_data = b.build()
        output, vr, insns = optimize_and_verify(input_data)
        assert vr["valid"] is True
        assert get_code_len(output) == get_code_len(input_data)
        assert len(insns) == 2
        assert insns[0][0] == OP_push_i32
        assert insns[1][0] == OP_return_val

    def test_loop_pass_through(self):
        """Complex loop with no optimization opportunities."""
        b = BytecodeBuilder(num_locals=1)
        b.push_i32(0)
        b.put_loc(0)
        b.label("LOOP")
        b.get_loc(0)
        b.push_i32(10)
        b.lt()
        b.if_false("END")
        b.get_loc(0)
        b.inc()
        b.put_loc(0)
        b.goto("LOOP")
        b.label("END")
        b.get_loc(0)
        b.return_val()
        input_data = b.build()
        output, vr, _insns = optimize_and_verify(input_data)
        assert vr["valid"] is True
        assert get_code_len(output) == get_code_len(input_data)


# ===================================================================
# Tests — constant folding
# ===================================================================

class TestConstantFolding:
    def test_fold_add(self):
        """push_i32 3; push_i32 4; add -> push_i32 7"""
        b = BytecodeBuilder()
        b.push_i32(3)
        b.push_i32(4)
        b.add()
        b.return_val()
        output, vr, insns = optimize_and_verify(b)
        assert vr["valid"] is True
        assert get_code_len(output) == 6  # push_i32(5) + return_val(1)
        assert insns[0][0] == OP_push_i32
        assert get_i32_operand(insns[0][1]) == 7
        assert insns[1][0] == OP_return_val

    def test_fold_sub(self):
        """push_i32 10; push_i32 3; sub -> push_i32 7"""
        b = BytecodeBuilder()
        b.push_i32(10)
        b.push_i32(3)
        b.sub()
        b.return_val()
        output, vr, insns = optimize_and_verify(b)
        assert vr["valid"] is True
        assert get_code_len(output) == 6
        assert get_i32_operand(insns[0][1]) == 7

    def test_fold_mul(self):
        """push_i32 6; push_i32 7; mul -> push_i32 42"""
        b = BytecodeBuilder()
        b.push_i32(6)
        b.push_i32(7)
        b.mul()
        b.return_val()
        output, vr, insns = optimize_and_verify(b)
        assert vr["valid"] is True
        assert get_code_len(output) == 6
        assert get_i32_operand(insns[0][1]) == 42

    def test_chained_fold(self):
        """Two rounds: push 1;push 2;add -> push 3; then push 3;push 3;mul -> push 9."""
        b = BytecodeBuilder()
        b.push_i32(1)
        b.push_i32(2)
        b.add()
        b.push_i32(3)
        b.mul()
        b.return_val()
        output, vr, insns = optimize_and_verify(b)
        assert vr["valid"] is True
        assert get_code_len(output) == 6
        assert get_i32_operand(insns[0][1]) == 9

    def test_fold_negative_result(self):
        """push_i32 5; push_i32 10; sub -> push_i32 -5"""
        b = BytecodeBuilder()
        b.push_i32(5)
        b.push_i32(10)
        b.sub()
        b.return_val()
        output, vr, insns = optimize_and_verify(b)
        assert vr["valid"] is True
        assert get_code_len(output) == 6
        assert get_i32_operand(insns[0][1]) == -5


# ===================================================================
# Tests — dead branch elimination
# ===================================================================

class TestDeadBranches:
    def test_true_if_false(self):
        """push_true; if_false L -> both deleted, code falls through."""
        b = BytecodeBuilder()
        b.push_true()
        b.if_false("L")
        b.push_i32(1)
        b.return_val()
        b.label("L")
        b.push_i32(2)
        b.return_val()
        output, vr, insns = optimize_and_verify(b)
        assert vr["valid"] is True
        # After dead branch + dead code: push_i32(1); return_val
        assert get_code_len(output) == 6
        assert get_i32_operand(insns[0][1]) == 1

    def test_false_if_false(self):
        """push_false; if_false L -> goto L (always branches)."""
        b = BytecodeBuilder()
        b.push_false()
        b.if_false("L")
        b.push_i32(1)
        b.return_val()
        b.label("L")
        b.push_i32(2)
        b.return_val()
        output, vr, insns = optimize_and_verify(b)
        assert vr["valid"] is True
        # goto + dead code removal leaves: goto_op; push_i32(2); return_val
        assert get_code_len(output) == 11
        assert insns[0][0] == OP_goto_op
        assert get_i32_operand(insns[1][1]) == 2

    def test_true_if_true(self):
        """push_true; if_true L -> goto L (always branches)."""
        b = BytecodeBuilder()
        b.push_true()
        b.if_true("L")
        b.push_i32(1)
        b.return_val()
        b.label("L")
        b.push_i32(2)
        b.return_val()
        output, vr, insns = optimize_and_verify(b)
        assert vr["valid"] is True
        assert get_code_len(output) == 11
        assert insns[0][0] == OP_goto_op
        assert get_i32_operand(insns[1][1]) == 2

    def test_false_if_true(self):
        """push_false; if_true L -> both deleted, falls through."""
        b = BytecodeBuilder()
        b.push_false()
        b.if_true("L")
        b.push_i32(1)
        b.return_val()
        b.label("L")
        b.push_i32(2)
        b.return_val()
        output, vr, insns = optimize_and_verify(b)
        assert vr["valid"] is True
        assert get_code_len(output) == 6
        assert get_i32_operand(insns[0][1]) == 1


# ===================================================================
# Tests — unreachable code elimination
# ===================================================================

class TestDeadCode:
    def test_after_return(self):
        """Dead code after return_val is removed."""
        b = BytecodeBuilder()
        b.push_i32(42)
        b.return_val()
        b.push_i32(0)
        b.drop()
        output, vr, insns = optimize_and_verify(b)
        assert vr["valid"] is True
        assert get_code_len(output) == 6  # push_i32 + return_val only
        assert len(insns) == 2

    def test_after_goto(self):
        """Dead code between goto and its target is removed."""
        b = BytecodeBuilder()
        b.goto("L")
        b.push_i32(0)   # dead
        b.drop()          # dead
        b.label("L")
        b.push_i32(1)
        b.return_val()
        output, vr, insns = optimize_and_verify(b)
        assert vr["valid"] is True
        assert get_code_len(output) == 11  # goto + push_i32 + return_val
        assert insns[0][0] == OP_goto_op
        assert insns[1][0] == OP_push_i32
        assert get_i32_operand(insns[1][1]) == 1

    def test_preserves_branch_targets(self):
        """Dead code stops at branch targets."""
        b = BytecodeBuilder()
        b.push_true()
        b.if_false("ELSE")
        b.push_i32(1)
        b.return_val()      # terminal
        b.label("ELSE")     # branch target — must be preserved
        b.push_i32(2)
        b.return_val()
        input_data = b.build()
        output, vr, _insns = optimize_and_verify(input_data)
        assert vr["valid"] is True
        # push_true+if_false both deleted -> dead code removes ELSE path
        assert get_code_len(output) == 6


# ===================================================================
# Tests — goto chain threading
# ===================================================================

class TestGotoThreading:
    def test_simple_chain(self):
        """goto L1; L1: goto L2; L2: return_undef -> thread to L2."""
        b = BytecodeBuilder()
        b.goto("L1")
        b.label("L1")
        b.goto("L2")
        b.label("L2")
        b.return_undef()
        output, vr, insns = optimize_and_verify(b)
        assert vr["valid"] is True
        assert get_code_len(output) < 11  # original is 11 bytes
        # Must end in return_undef
        assert insns[-1][0] == OP_return_undef

    def test_deep_chain(self):
        """Thread through 3 levels of gotos."""
        b = BytecodeBuilder()
        b.goto("L1")
        b.label("L1")
        b.goto("L2")
        b.label("L2")
        b.goto("L3")
        b.label("L3")
        b.push_i32(99)
        b.return_val()
        output, vr, insns = optimize_and_verify(b)
        assert vr["valid"] is True
        # After threading + dead code: goto + push_i32(99) + return_val
        assert get_code_len(output) == 11
        assert insns[0][0] == OP_goto_op
        assert insns[1][0] == OP_push_i32
        assert get_i32_operand(insns[1][1]) == 99

    def test_thread_conditional(self):
        """if_false target is a goto -> thread it; dead goto removed."""
        b = BytecodeBuilder()
        b.push_true()
        b.dup()
        b.if_false("L1")
        b.return_val()
        b.label("L1")
        b.goto("L2")
        b.label("L2")
        b.return_val()
        input_data = b.build()
        output, vr, _insns = optimize_and_verify(input_data)
        assert vr["valid"] is True
        # After threading, if_false targets L2 directly; goto at L1 becomes
        # dead code (after return_val terminal, no longer a branch target).
        assert get_code_len(output) < get_code_len(input_data)


# ===================================================================
# Tests — push-drop elimination
# ===================================================================

class TestPushDrop:
    def test_push_i32_drop(self):
        """push_i32 42; drop -> both removed."""
        b = BytecodeBuilder()
        b.push_i32(42)
        b.drop()
        b.return_undef()
        output, vr, insns = optimize_and_verify(b)
        assert vr["valid"] is True
        assert get_code_len(output) == 1  # only return_undef
        assert len(insns) == 1
        assert insns[0][0] == OP_return_undef

    def test_push_true_drop(self):
        """push_true; drop -> both removed."""
        b = BytecodeBuilder()
        b.push_true()
        b.drop()
        b.push_i32(7)
        b.return_val()
        output, vr, insns = optimize_and_verify(b)
        assert vr["valid"] is True
        assert get_code_len(output) == 6
        assert insns[0][0] == OP_push_i32
        assert get_i32_operand(insns[0][1]) == 7

    def test_undefined_drop(self):
        """undefined; drop -> both removed."""
        b = BytecodeBuilder()
        b.undefined()
        b.drop()
        b.return_undef()
        output, vr, insns = optimize_and_verify(b)
        assert vr["valid"] is True
        assert get_code_len(output) == 1


# ===================================================================
# Tests — combined optimizations
# ===================================================================

class TestCombined:
    def test_fold_then_push_drop(self):
        """Folding creates a push that's immediately dropped."""
        b = BytecodeBuilder()
        b.push_i32(1)
        b.push_i32(2)
        b.add()
        b.drop()
        b.return_undef()
        # Round 1: fold -> push_i32(3); drop; return_undef
        # Round 2: push-drop -> return_undef
        output, vr, insns = optimize_and_verify(b)
        assert vr["valid"] is True
        assert get_code_len(output) == 1
        assert insns[0][0] == OP_return_undef

    def test_branch_elim_fold_dead(self):
        """Dead branch + constant fold + dead code work together."""
        b = BytecodeBuilder()
        b.push_true()
        b.if_false("ELSE")
        b.push_i32(10)
        b.push_i32(20)
        b.add()
        b.return_val()
        b.label("ELSE")
        b.push_i32(99)
        b.return_val()
        output, vr, insns = optimize_and_verify(b)
        assert vr["valid"] is True
        assert get_code_len(output) == 6  # push_i32(30) + return_val
        assert get_i32_operand(insns[0][1]) == 30

    def test_multiple_push_drops(self):
        """Several push-drop pairs in sequence."""
        b = BytecodeBuilder()
        b.push_i32(1)
        b.drop()
        b.push_true()
        b.drop()
        b.null_val()
        b.drop()
        b.push_i32(42)
        b.return_val()
        output, vr, insns = optimize_and_verify(b)
        assert vr["valid"] is True
        assert get_code_len(output) == 6
        assert get_i32_operand(insns[0][1]) == 42


# ===================================================================
# Tests — exception handler correctness
# ===================================================================

class TestExceptionHandlers:
    def test_catch_no_change(self):
        """Exception handler with no optimization opportunities."""
        b = BytecodeBuilder()
        b.catch("H")
        b.push_i32(42)
        b.end_catch()
        b.return_val()
        b.label("H")
        b.drop()
        b.push_i32(-1)
        b.return_val()
        input_data = b.build()
        output, vr, _insns = optimize_and_verify(input_data)
        assert vr["valid"] is True
        assert get_code_len(output) == get_code_len(input_data)

    def test_fold_in_try_body(self):
        """Constant fold inside a try block; handler offset must update."""
        b = BytecodeBuilder()
        b.catch("H")         # 0: 5 bytes
        b.push_i32(10)       # 5: 5 bytes
        b.push_i32(20)       # 10: 5 bytes
        b.add()               # 15: 1 byte  -> fold
        b.end_catch()         # 16: 1 byte
        b.return_val()        # 17: 1 byte
        b.label("H")
        b.return_val()        # 18: 1 byte (handler returns exception)
        # After fold: push_i32(10) becomes push_i32(30), delete 10&15
        # Original code_len = 19, after fold = 13
        output, vr, insns = optimize_and_verify(b)
        assert vr["valid"] is True
        assert get_code_len(output) == 13
        # Verify the handler entry is still valid
        assert vr["max_stack"] is not None

    def test_catch_with_nonzero_depth(self):
        """catch when stack already has values — handler depth correct."""
        b = BytecodeBuilder()
        b.push_i32(99)       # 0: 0->1
        b.catch("H")         # 5: depth 1, handler entry = 2
        b.push_i32(0)        # 10: 1->2
        b.end_catch()        # 15: 2
        b.add()              # 16: 2->1
        b.return_val()       # 17: 1
        b.label("H")
        b.add()              # 18: 2->1 (handler entry depth=2)
        b.return_val()       # 19: 1
        input_data = b.build()
        output, vr, _insns = optimize_and_verify(input_data)
        assert vr["valid"] is True
        # No optimization opportunities, identity transform
        assert get_code_len(output) == get_code_len(input_data)


# ===================================================================
# Tests — loop with optimization
# ===================================================================

class TestLoopOptimization:
    def test_fold_in_loop_body(self):
        """Constant folding inside a loop; backward branch recomputed."""
        b = BytecodeBuilder(num_locals=1)
        b.push_i32(0)        # 0: 5
        b.put_loc(0)          # 5: 3
        b.label("LOOP")
        b.get_loc(0)          # 8: 3
        b.push_i32(5)         # 11: 5  -> fold target
        b.push_i32(5)         # 16: 5  -> deleted
        b.add()                # 21: 1  -> deleted
        b.lt()                 # 22: 1
        b.if_false("END")     # 23: 5
        b.get_loc(0)          # 28: 3
        b.inc()                # 31: 1
        b.put_loc(0)          # 32: 3
        b.goto("LOOP")        # 35: 5
        b.label("END")
        b.get_loc(0)          # 40: 3
        b.return_val()        # 43: 1
        # Original: 44 bytes, after fold: 38 bytes
        output, vr, insns = optimize_and_verify(b)
        assert vr["valid"] is True
        assert get_code_len(output) == 38
        assert vr["max_stack"] == 2
        # Verify backward branch still works (program reaches END)
        opcodes = [i[0] for i in insns]
        assert OP_goto_op in opcodes
        assert OP_if_false in opcodes
