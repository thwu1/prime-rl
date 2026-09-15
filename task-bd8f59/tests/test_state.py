
import pytest
import sys
import os

sys.path.insert(0, '/app')

from rv32i_analyzer import decode_instruction, simulate, find_trace_errors, analyze_pipeline_hazards


def load_program(filepath):
    program = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line:
                program.append(int(line, 16))
    return program


def parse_trace_csv(filepath):
    entries = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(';')
            pc = int(parts[0], 16)
            instruction = int(parts[1], 16)
            if len(parts) >= 4 and parts[2].strip() and parts[3].strip():
                rd = int(parts[2])
                rd_value = int(parts[3], 16)
            else:
                rd = None
                rd_value = None
            entries.append({
                'pc': pc,
                'instruction': instruction,
                'rd': rd,
                'rd_value': rd_value,
            })
    return entries


# ============================================================
# Decode tests
# ============================================================

class TestDecode:
    def test_r_type_add(self):
        # add x3, x1, x2 = 0x002081b3
        r = decode_instruction(0x002081b3)
        assert r['type'] == 'R'
        assert r['rd'] == 3
        assert r['rs1'] == 1
        assert r['rs2'] == 2
        assert r['funct3'] == 0
        assert r['funct7'] == 0
        assert r['name'] == 'add'

    def test_r_type_sub(self):
        # sub x4, x1, x2 = 0x40208233
        r = decode_instruction(0x40208233)
        assert r['type'] == 'R'
        assert r['rd'] == 4
        assert r['rs1'] == 1
        assert r['rs2'] == 2
        assert r['funct7'] == 0x20
        assert r['name'] == 'sub'

    def test_r_type_sra(self):
        # sra x5, x1, x2 = 0x4020d2b3
        r = decode_instruction(0x4020d2b3)
        assert r['type'] == 'R'
        assert r['name'] == 'sra'
        assert r['funct7'] == 0x20
        assert r['funct3'] == 5

    def test_i_type_addi_positive(self):
        # addi x1, x0, 5 = 0x00500093
        r = decode_instruction(0x00500093)
        assert r['type'] == 'I'
        assert r['rd'] == 1
        assert r['rs1'] == 0
        assert r['imm'] == 5
        assert r['name'] == 'addi'

    def test_i_type_addi_negative(self):
        # addi x1, x0, -1 = 0xfff00093
        r = decode_instruction(0xfff00093)
        assert r['type'] == 'I'
        assert r['rd'] == 1
        assert r['rs1'] == 0
        assert r['imm'] == -1
        assert r['name'] == 'addi'

    def test_i_type_slli(self):
        # slli x10, x1, 2 = 0x00209513
        r = decode_instruction(0x00209513)
        assert r['type'] == 'I'
        assert r['rd'] == 10
        assert r['rs1'] == 1
        assert r['funct3'] == 1
        assert r['imm'] == 2  # shamt
        assert r['name'] == 'slli'

    def test_i_type_srai(self):
        # srai x12, x2, 1 = 0x40115613
        r = decode_instruction(0x40115613)
        assert r['type'] == 'I'
        assert r['rd'] == 12
        assert r['rs1'] == 2
        assert r['funct3'] == 5
        assert r['funct7'] == 0x20
        assert r['imm'] == 1  # shamt
        assert r['name'] == 'srai'

    def test_i_type_load_lw(self):
        # lw x3, 0(x1) = 0x0000a183
        r = decode_instruction(0x0000a183)
        assert r['type'] == 'I'
        assert r['rd'] == 3
        assert r['rs1'] == 1
        assert r['funct3'] == 2  # LW
        assert r['imm'] == 0
        assert r['name'] == 'lw'

    def test_i_type_jalr(self):
        # jalr x0, x5, 0 = 0x00028067
        r = decode_instruction(0x00028067)
        assert r['type'] == 'I'
        assert r['rd'] == 0
        assert r['rs1'] == 5
        assert r['imm'] == 0
        assert r['name'] == 'jalr'

    def test_s_type_sw(self):
        # sw x2, 0(x1) = 0x0020a023
        r = decode_instruction(0x0020a023)
        assert r['type'] == 'S'
        assert r['rs1'] == 1
        assert r['rs2'] == 2
        assert r['funct3'] == 2  # SW
        assert r['imm'] == 0
        assert r['name'] == 'sw'

    def test_s_type_sw_offset(self):
        # sw x4, 4(x1) = 0x0040a223
        r = decode_instruction(0x0040a223)
        assert r['type'] == 'S'
        assert r['rs1'] == 1
        assert r['rs2'] == 4
        assert r['imm'] == 4
        assert r['name'] == 'sw'

    def test_b_type_beq_positive(self):
        # beq x1, x2, +12 = 0x00208663
        r = decode_instruction(0x00208663)
        assert r['type'] == 'B'
        assert r['rs1'] == 1
        assert r['rs2'] == 2
        assert r['funct3'] == 0
        assert r['imm'] == 12
        assert r['name'] == 'beq'

    def test_b_type_bge_negative(self):
        # bge x2, x3, -8 = 0xfe315ce3
        r = decode_instruction(0xfe315ce3)
        assert r['type'] == 'B'
        assert r['rs1'] == 2
        assert r['rs2'] == 3
        assert r['funct3'] == 5  # BGE
        assert r['imm'] == -8
        assert r['name'] == 'bge'

    def test_u_type_lui(self):
        # lui x13, 0x12345 = 0x123456b7
        r = decode_instruction(0x123456b7)
        assert r['type'] == 'U'
        assert r['rd'] == 13
        assert r['imm'] == 0x12345000
        assert r['name'] == 'lui'

    def test_u_type_auipc(self):
        # auipc x14, 0x1000 = 0x01000717
        r = decode_instruction(0x01000717)
        assert r['type'] == 'U'
        assert r['rd'] == 14
        assert r['imm'] == 0x01000000
        assert r['name'] == 'auipc'

    def test_j_type_jal(self):
        # jal x5, +12 = 0x00c002ef
        r = decode_instruction(0x00c002ef)
        assert r['type'] == 'J'
        assert r['rd'] == 5
        assert r['imm'] == 12
        assert r['name'] == 'jal'

    def test_ecall(self):
        # ecall = 0x00000073
        r = decode_instruction(0x00000073)
        assert r['name'] == 'ecall'


# ============================================================
# Simulation tests
# ============================================================

class TestSimulate:
    def test_arithmetic(self):
        program = load_program('/app/programs/arithmetic.hex')
        result = simulate(program)
        regs = result['registers']
        assert regs[0] == 0, "x0 must be 0"
        assert regs[1] == 5, "addi x1, x0, 5"
        assert regs[2] == 7, "addi x2, x0, 7"
        assert regs[3] == 12, "add x3, x1, x2"
        assert regs[4] == 0xfffffffe, "sub x4, x1, x2 = -2"
        assert regs[5] == 5, "and x5, x1, x2 = 5 & 7"
        assert regs[6] == 7, "or x6, x1, x2 = 5 | 7"
        assert regs[7] == 2, "xor x7, x1, x2 = 5 ^ 7"
        assert regs[8] == 1, "slt x8: 5 < 7 signed"
        assert regs[9] == 1, "sltu x9: 5 < 7 unsigned"
        assert regs[10] == 20, "slli x10, x1, 2 = 5 << 2"
        assert regs[11] == 3, "srli x11, x2, 1 = 7 >> 1"
        assert regs[12] == 3, "srai x12, x2, 1 = 7 >>> 1"
        assert regs[13] == 0x12345000, "lui x13, 0x12345"
        assert regs[14] == 0x01000034, "auipc x14, 0x1000 at PC=0x34"

    def test_branches(self):
        program = load_program('/app/programs/branches.hex')
        result = simulate(program)
        regs = result['registers']
        assert regs[1] == 0x0a, "x1 = 10"
        assert regs[2] == 0xffffffff, "x2 = -1"
        assert regs[3] == 1, "x3 = 1"
        assert regs[4] == 0x2a, "x4 = 42 (after bne jump)"
        assert regs[5] == 0x4d, "x5 = 77 (after blt jump)"
        assert regs[6] == 0x21, "x6 = 33 (after bge jump)"

    def test_loop_sum(self):
        program = load_program('/app/programs/loop.hex')
        result = simulate(program)
        regs = result['registers']
        assert regs[1] == 15, "sum 1+2+3+4+5 = 15"
        assert regs[2] == 5, "limit unchanged"
        assert regs[3] == 6, "counter exited at 6"
        assert result['steps'] == 19, "loop executes 19 instructions total"

    def test_calls_jal_jalr(self):
        program = load_program('/app/programs/calls.hex')
        result = simulate(program)
        regs = result['registers']
        assert regs[1] == 3, "x1 = 3 (argument)"
        assert regs[2] == 6, "x2 = 3+3 = 6 (doubled)"
        assert regs[5] == 8, "x5 = return address from jal"
        assert regs[10] == 0, "x10 = 0"

    def test_signed_operations(self):
        program = load_program('/app/programs/signed.hex')
        result = simulate(program)
        regs = result['registers']
        assert regs[1] == 0xffffffff, "x1 = -1"
        assert regs[2] == 1
        assert regs[3] == 1, "slt: -1 < 1 (signed)"
        assert regs[4] == 0, "sltu: 0xFFFFFFFF not < 1 (unsigned)"
        assert regs[5] == 1
        assert regs[6] == 2
        assert regs[7] == 0x80000000, "lui 0x80000"
        assert regs[8] == 1, "slt: MIN_INT < 1"
        assert regs[9] == 0, "sltu: 0x80000000 not < 1"
        assert regs[10] == 0xffff8000, "srai x7, 16 (arithmetic shift)"
        assert regs[11] == 0x00008000, "srli x7, 16 (logical shift)"
        assert regs[12] == 0, "xori: 0xFFFFFFFF ^ -1 = 0"
        assert regs[13] == 0xffffffff, "ori: 0 | -1"
        assert regs[14] == 0x7f, "andi: 0xFFFFFFFF & 0x7F"
        assert regs[15] == 1, "slti: -1 < 0"
        assert regs[16] == 0, "sltiu: 0xFFFFFFFF not < 1 (unsigned)"

    def test_memory_operations(self):
        program = load_program('/app/programs/memory.hex')
        result = simulate(program)
        regs = result['registers']
        assert regs[1] == 0x00010000, "lui x1, 0x10"
        assert regs[2] == 0x42, "x2 = 0x42"
        assert regs[3] == 0x42, "lw: loaded back stored word"
        assert regs[4] == 0xffffffff, "x4 = -1"
        assert regs[5] == 0xffffffff, "lb: sign-ext of 0xFF"
        assert regs[6] == 0x000000ff, "lbu: zero-ext of 0xFF"
        assert regs[7] == 0x00000042, "lh: sign-ext of 0x0042"
        assert regs[8] == 0x00000042, "lhu: zero-ext of 0x0042"
        assert regs[9] == 0x000000ff, "lbu: byte from sb"

    def test_loaduse_simulation(self):
        program = load_program('/app/programs/hazard_loaduse.hex')
        result = simulate(program)
        regs = result['registers']
        assert regs[1] == 0x00010000, "lui x1, 0x10"
        assert regs[2] == 42, "addi x2, x0, 42"
        assert regs[3] == 42, "lw x3 = stored value"
        assert regs[4] == 84, "add x4, x3, x2 = 42 + 42"

    def test_trace_length_arithmetic(self):
        program = load_program('/app/programs/arithmetic.hex')
        result = simulate(program)
        assert result['steps'] == 15, "arithmetic program is 15 steps"
        assert len(result['trace']) == 15

    def test_trace_content_calls(self):
        program = load_program('/app/programs/calls.hex')
        result = simulate(program)
        trace = result['trace']
        # Step 1: jal x5, +12 at PC=0x04 -> x5=0x08
        assert trace[1]['pc'] == 0x04
        assert trace[1]['rd'] == 5
        assert trace[1]['rd_value'] == 0x08
        # Step 2 should be at PC=0x10 (jumped)
        assert trace[2]['pc'] == 0x10
        # Step 3: jalr x0, x5, 0 at PC=0x14 -> returns to 0x08
        assert trace[3]['pc'] == 0x14
        assert trace[3]['rd'] == 0
        assert trace[3]['rd_value'] == 0  # x0 always 0
        # Step 4: back at PC=0x08
        assert trace[4]['pc'] == 0x08


# ============================================================
# Trace error detection tests
# ============================================================

class TestTraceErrors:
    def test_correct_trace_no_errors(self):
        program = load_program('/app/programs/arithmetic.hex')
        trace = parse_trace_csv('/app/traces/arithmetic_correct.csv')
        errors = find_trace_errors(program, trace)
        assert len(errors) == 0, "correct trace should have zero errors"

    def test_arithmetic_corrupted(self):
        program = load_program('/app/programs/arithmetic.hex')
        trace = parse_trace_csv('/app/traces/arithmetic_corrupted.csv')
        errors = find_trace_errors(program, trace)
        assert len(errors) == 3, f"expected 3 errors, got {len(errors)}"

        # Error at step 2: add x3 should be 0xC not 0x5
        e2 = [e for e in errors if e['step'] == 2]
        assert len(e2) == 1
        assert e2[0]['field'] == 'rd_value'
        assert e2[0]['expected'] == 0x0000000c
        assert e2[0]['actual'] == 0x00000005

        # Error at step 7: slt x8 should be 1 not 0
        e7 = [e for e in errors if e['step'] == 7]
        assert len(e7) == 1
        assert e7[0]['field'] == 'rd_value'
        assert e7[0]['expected'] == 0x00000001
        assert e7[0]['actual'] == 0x00000000

        # Error at step 13: auipc x14 should be 0x01000034 not 0x01000000
        e13 = [e for e in errors if e['step'] == 13]
        assert len(e13) == 1
        assert e13[0]['field'] == 'rd_value'
        assert e13[0]['expected'] == 0x01000034
        assert e13[0]['actual'] == 0x01000000

    def test_signed_corrupted(self):
        program = load_program('/app/programs/signed.hex')
        trace = parse_trace_csv('/app/traces/signed_corrupted.csv')
        errors = find_trace_errors(program, trace)
        assert len(errors) == 3, f"expected 3 errors, got {len(errors)}"

        error_steps = sorted([e['step'] for e in errors])
        assert error_steps == [3, 11, 17], f"errors at wrong steps: {error_steps}"

        # Step 3: sltu should be 0 not 1
        e3 = [e for e in errors if e['step'] == 3][0]
        assert e3['expected'] == 0x00000000
        assert e3['actual'] == 0x00000001

        # Step 11: srai should be 0xffff8000 not 0x00008000
        e11 = [e for e in errors if e['step'] == 11][0]
        assert e11['expected'] == 0xffff8000
        assert e11['actual'] == 0x00008000

        # Step 17: sltiu should be 0 not 1
        e17 = [e for e in errors if e['step'] == 17][0]
        assert e17['expected'] == 0x00000000
        assert e17['actual'] == 0x00000001

    def test_branches_correct(self):
        program = load_program('/app/programs/branches.hex')
        trace = parse_trace_csv('/app/traces/branches_correct.csv')
        errors = find_trace_errors(program, trace)
        assert len(errors) == 0

    def test_loop_correct(self):
        program = load_program('/app/programs/loop.hex')
        trace = parse_trace_csv('/app/traces/loop_correct.csv')
        errors = find_trace_errors(program, trace)
        assert len(errors) == 0

    def test_memory_correct(self):
        program = load_program('/app/programs/memory.hex')
        trace = parse_trace_csv('/app/traces/memory_correct.csv')
        errors = find_trace_errors(program, trace)
        assert len(errors) == 0

    def test_loaduse_correct(self):
        program = load_program('/app/programs/hazard_loaduse.hex')
        trace = parse_trace_csv('/app/traces/hazard_loaduse_correct.csv')
        errors = find_trace_errors(program, trace)
        assert len(errors) == 0


# ============================================================
# Pipeline hazard analysis tests
# ============================================================

class TestPipelineHazards:
    def test_arithmetic_hazards(self):
        program = load_program('/app/programs/arithmetic.hex')
        hazards = analyze_pipeline_hazards(program)
        relevant = [h for h in hazards if h['distance'] <= 2]

        assert len(relevant) == 3, f"expected 3 hazards, got {len(relevant)}: {relevant}"

        # Check the distance-1 hazard
        d1 = [h for h in relevant if h['distance'] == 1]
        assert len(d1) == 1
        assert d1[0]['consumer_index'] == 2
        assert d1[0]['producer_index'] == 1
        assert d1[0]['register'] == 2
        assert d1[0]['type'] == 'RAW'
        assert d1[0]['stalls_no_forwarding'] == 2
        assert d1[0]['stalls_with_forwarding'] == 0

        # Check the distance-2 hazards
        d2 = sorted([h for h in relevant if h['distance'] == 2],
                     key=lambda h: (h['consumer_index'], h['register']))
        assert len(d2) == 2
        for h in d2:
            assert h['stalls_no_forwarding'] == 1
            assert h['stalls_with_forwarding'] == 0

    def test_loop_hazards(self):
        program = load_program('/app/programs/loop.hex')
        hazards = analyze_pipeline_hazards(program)
        relevant = [h for h in hazards if h['distance'] <= 2]

        assert len(relevant) == 3, f"expected 3 hazards, got {len(relevant)}: {relevant}"

        # Verify the bge hazard (consumer=5, producer=4)
        bge_haz = [h for h in relevant if h['consumer_index'] == 5]
        assert len(bge_haz) == 1
        assert bge_haz[0]['producer_index'] == 4
        assert bge_haz[0]['register'] == 3
        assert bge_haz[0]['distance'] == 1
        assert bge_haz[0]['stalls_no_forwarding'] == 2
        assert bge_haz[0]['stalls_with_forwarding'] == 0

    def test_calls_no_stall_hazards(self):
        # calls.hex has no hazards with distance <= 2
        program = load_program('/app/programs/calls.hex')
        hazards = analyze_pipeline_hazards(program)
        relevant = [h for h in hazards if h['distance'] <= 2]
        assert len(relevant) == 0, f"expected 0 hazards, got {len(relevant)}"

    def test_loaduse_hazards(self):
        program = load_program('/app/programs/hazard_loaduse.hex')
        hazards = analyze_pipeline_hazards(program)
        relevant = [h for h in hazards if h['distance'] <= 2]

        assert len(relevant) == 3, f"expected 3 hazards, got {len(relevant)}: {relevant}"

        # Find the load-use hazard specifically
        load_use = [h for h in relevant
                     if h['consumer_index'] == 4 and h['register'] == 3]
        assert len(load_use) == 1, "should have one load-use hazard"
        h = load_use[0]
        assert h['producer_index'] == 3
        assert h['distance'] == 1
        assert h['type'] == 'RAW'
        assert h['stalls_no_forwarding'] == 2
        assert h['stalls_with_forwarding'] == 1, \
            "load-use hazard requires 1 stall even with forwarding"

        # Verify ALU hazards have 0 stalls with forwarding
        alu_haz = [h for h in relevant if h['consumer_index'] == 2]
        assert len(alu_haz) == 2
        for ah in alu_haz:
            assert ah['stalls_with_forwarding'] == 0, \
                "ALU-to-ALU hazards need 0 stalls with forwarding"
