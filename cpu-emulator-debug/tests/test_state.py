"""Verification tests for 6502 CPU emulator conformance certification.

"""

import json
import sqlite3
import sys
import importlib.util
import os


def load_cpu_class(path, module_name):
    """Load a CPU6502 class from a specific file path."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.CPU6502


FixedCPU = load_cpu_class('/app/cpu6502.py', 'cpu6502_fixed')
OriginalCPU = load_cpu_class('/app/cpu6502_original.py', 'cpu6502_original')


def make_cpu(cls, pc, a=0, x=0, y=0, sp=0xFD, p=0x20, ram=None):
    """Create a CPU instance with given initial state."""
    cpu = cls()
    cpu.PC = pc
    cpu.A = a
    cpu.X = x
    cpu.Y = y
    cpu.SP = sp
    cpu.set_status_byte(p)
    cpu.memory = bytearray(65536)
    if ram:
        for addr, val in ram:
            cpu.memory[addr] = val
    return cpu


def run_test_case(cpu_class, test):
    """Run a SingleStepTests test case. Returns (passed, error_list)."""
    cpu = cpu_class()
    cpu.load_state(test['initial'])
    cpu.step()
    state = cpu.get_state()
    expected = test['final']
    errors = []
    for key in ['pc', 's', 'a', 'x', 'y', 'p']:
        if state[key] != expected[key]:
            errors.append(f"{key}: expected {expected[key]}, got {state[key]}")
    for addr, val in expected.get('ram', []):
        actual = cpu.memory[addr]
        if actual != val:
            errors.append(f"mem[{addr}]: expected {val}, got {actual}")
    return (len(errors) == 0, errors)


# ============================================================
# Bug area 1: Zero-page indexed X wrapping
# ============================================================
class TestZeroPageXWrapping:
    def test_lda_zpx_wraps_ff_plus_1(self):
        cpu = make_cpu(FixedCPU, 0x0200, x=1, ram=[
            (0x0200, 0xB5), (0x0201, 0xFF),
            (0x0000, 0x42), (0x0100, 0x99),
        ])
        cpu.step()
        assert cpu.A == 0x42, f"LDA zp,X: base=FF X=1 should wrap to 0x00, got A=0x{cpu.A:02X}"

    def test_lda_zpx_wraps_80_plus_80(self):
        cpu = make_cpu(FixedCPU, 0x0200, x=0x80, ram=[
            (0x0200, 0xB5), (0x0201, 0x80),
            (0x0000, 0xBB), (0x0100, 0xDD),
        ])
        cpu.step()
        assert cpu.A == 0xBB

    def test_sta_zpx_wraps(self):
        cpu = make_cpu(FixedCPU, 0x0200, a=0xAB, x=0x05, ram=[
            (0x0200, 0x95), (0x0201, 0xFE),
        ])
        cpu.step()
        assert cpu.memory[0x03] == 0xAB

    def test_adc_zpx_wraps(self):
        cpu = make_cpu(FixedCPU, 0x0200, a=0x10, x=0x03, ram=[
            (0x0200, 0x75), (0x0201, 0xFE),
            (0x0001, 0x05), (0x0101, 0x50),
        ])
        cpu.step()
        assert cpu.A == 0x15


# ============================================================
# Bug area 2: Indirect JMP page boundary wrapping
# ============================================================
class TestIndirectJMPPageBoundary:
    def test_jmp_indirect_page_wrap(self):
        cpu = make_cpu(FixedCPU, 0x0300, ram=[
            (0x0300, 0x6C), (0x0301, 0xFF), (0x0302, 0x10),
            (0x10FF, 0x34), (0x1000, 0x56), (0x1100, 0x12),
        ])
        cpu.step()
        assert cpu.PC == 0x5634, f"JMP ($10FF) should wrap high byte read, got PC=0x{cpu.PC:04X}"

    def test_jmp_indirect_page_wrap_2(self):
        cpu = make_cpu(FixedCPU, 0x0300, ram=[
            (0x0300, 0x6C), (0x0301, 0xFF), (0x0302, 0x20),
            (0x20FF, 0xAA), (0x2000, 0xBB), (0x2100, 0xCC),
        ])
        cpu.step()
        assert cpu.PC == 0xBBAA

    def test_jmp_indirect_normal(self):
        cpu = make_cpu(FixedCPU, 0x0300, ram=[
            (0x0300, 0x6C), (0x0301, 0x50), (0x0302, 0x10),
            (0x1050, 0x00), (0x1051, 0x80),
        ])
        cpu.step()
        assert cpu.PC == 0x8000


# ============================================================
# Bug area 3: BCD ADC low nibble threshold
# ============================================================
class TestBCDADC:
    def test_bcd_5_plus_5(self):
        cpu = make_cpu(FixedCPU, 0x0200, a=0x05, p=0x28, ram=[
            (0x0200, 0x69), (0x0201, 0x05),
        ])
        cpu.step()
        assert cpu.A == 0x10, f"BCD 05+05=10, got 0x{cpu.A:02X}"

    def test_bcd_9_plus_1(self):
        cpu = make_cpu(FixedCPU, 0x0200, a=0x09, p=0x28, ram=[
            (0x0200, 0x69), (0x0201, 0x01),
        ])
        cpu.step()
        assert cpu.A == 0x10

    def test_bcd_58_plus_46(self):
        cpu = make_cpu(FixedCPU, 0x0200, a=0x58, p=0x28, ram=[
            (0x0200, 0x69), (0x0201, 0x46),
        ])
        cpu.step()
        assert cpu.A == 0x04
        assert cpu.C is True

    def test_bcd_no_adjust_needed(self):
        cpu = make_cpu(FixedCPU, 0x0200, a=0x12, p=0x28, ram=[
            (0x0200, 0x69), (0x0201, 0x34),
        ])
        cpu.step()
        assert cpu.A == 0x46


# ============================================================
# Bug area 4: ROL carry order
# ============================================================
class TestROLCarry:
    def test_rol_a_carry_0_bit7_1(self):
        cpu = make_cpu(FixedCPU, 0x0200, a=0x80, p=0x20, ram=[
            (0x0200, 0x2A),
        ])
        cpu.step()
        assert cpu.A == 0x00, f"ROL 0x80 C=0: expected 0x00, got 0x{cpu.A:02X}"
        assert cpu.C is True
        assert cpu.Z is True

    def test_rol_a_carry_1_bit7_0(self):
        cpu = make_cpu(FixedCPU, 0x0200, a=0x40, p=0x21, ram=[
            (0x0200, 0x2A),
        ])
        cpu.step()
        assert cpu.A == 0x81
        assert cpu.C is False
        assert cpu.N is True

    def test_rol_mem_carry_0_bit7_1(self):
        cpu = make_cpu(FixedCPU, 0x0200, p=0x20, ram=[
            (0x0200, 0x26), (0x0201, 0x50),
            (0x0050, 0x80),
        ])
        cpu.step()
        assert cpu.memory[0x50] == 0x00
        assert cpu.C is True

    def test_rol_mem_carry_1_bit7_0(self):
        cpu = make_cpu(FixedCPU, 0x0200, p=0x21, ram=[
            (0x0200, 0x26), (0x0201, 0x50),
            (0x0050, 0x40),
        ])
        cpu.step()
        assert cpu.memory[0x50] == 0x81
        assert cpu.C is False


# ============================================================
# Bug area 5: BRK PC push
# ============================================================
class TestBRKPCPush:
    def test_brk_pushes_pc_plus_2(self):
        cpu = make_cpu(FixedCPU, 0x0300, sp=0xFD, p=0x20, ram=[
            (0x0300, 0x00), (0x0301, 0xEA),
            (0xFFFE, 0x00), (0xFFFF, 0x80),
        ])
        cpu.step()
        assert cpu.PC == 0x8000
        assert cpu.memory[0x01FD] == 0x03, "BRK: high byte of return addr"
        assert cpu.memory[0x01FC] == 0x02, f"BRK: low byte should be 0x02, got 0x{cpu.memory[0x01FC]:02X}"

    def test_brk_sets_i_flag(self):
        cpu = make_cpu(FixedCPU, 0x0300, sp=0xFD, p=0x20, ram=[
            (0x0300, 0x00), (0x0301, 0x00),
            (0xFFFE, 0x00), (0xFFFF, 0x80),
        ])
        cpu.step()
        assert cpu.I is True

    def test_brk_pushes_status_with_b(self):
        cpu = make_cpu(FixedCPU, 0x0300, sp=0xFD, p=0x20, ram=[
            (0x0300, 0x00), (0x0301, 0x00),
            (0xFFFE, 0x00), (0xFFFF, 0x80),
        ])
        cpu.step()
        pushed_p = cpu.memory[0x01FB]
        assert pushed_p & 0x10, "BRK should push status with B flag set"


# ============================================================
# Bug area 6: Indexed indirect X zero-page wrapping
# ============================================================
class TestIZXWrapping:
    def test_lda_izx_ptr_at_ff(self):
        cpu = make_cpu(FixedCPU, 0x0200, x=0x0F, ram=[
            (0x0200, 0xA1), (0x0201, 0xF0),
            (0x00FF, 0x34), (0x0000, 0x12),
            (0x0100, 0x56),
            (0x1234, 0x42),
        ])
        cpu.step()
        assert cpu.A == 0x42, (
            f"LDA (zp,X) ptr=0xFF: high byte should come from 0x00, got A=0x{cpu.A:02X}"
        )

    def test_sta_izx_ptr_at_ff(self):
        cpu = make_cpu(FixedCPU, 0x0200, a=0x77, x=0x01, ram=[
            (0x0200, 0x81), (0x0201, 0xFE),
            (0x00FF, 0x00), (0x0000, 0x05),
            (0x0100, 0x09),
        ])
        cpu.step()
        assert cpu.memory[0x0500] == 0x77, (
            "STA (zp,X) ptr=0xFF: should store at addr from zero-page wrap"
        )

    def test_lda_izx_no_wrap_needed(self):
        cpu = make_cpu(FixedCPU, 0x0200, x=5, ram=[
            (0x0200, 0xA1), (0x0201, 0x10),
            (0x0015, 0x00), (0x0016, 0x03),
            (0x0300, 0x55),
        ])
        cpu.step()
        assert cpu.A == 0x55


# ============================================================
# Bug area 7: SBC binary overflow flag
# ============================================================
class TestSBCOverflow:
    def test_sbc_positive_minus_negative_overflow(self):
        """0x50 - 0x90 = 0xC0; positive - negative = negative -> V=1"""
        cpu = make_cpu(FixedCPU, 0x0200, a=0x50, p=0x21, ram=[
            (0x0200, 0xE9), (0x0201, 0x90),
        ])
        cpu.step()
        assert cpu.A == 0xC0
        assert cpu.V is True, "SBC: pos - neg = neg should set V"
        assert cpu.N is True
        assert cpu.C is False

    def test_sbc_negative_minus_positive_overflow(self):
        """0x80 - 0x01 = 0x7F; negative - positive = positive -> V=1"""
        cpu = make_cpu(FixedCPU, 0x0200, a=0x80, p=0x21, ram=[
            (0x0200, 0xE9), (0x0201, 0x01),
        ])
        cpu.step()
        assert cpu.A == 0x7F
        assert cpu.V is True, "SBC: neg - pos = pos should set V"
        assert cpu.N is False
        assert cpu.C is True

    def test_sbc_same_sign_no_overflow(self):
        """0x50 - 0x30 = 0x20; same sign -> V=0"""
        cpu = make_cpu(FixedCPU, 0x0200, a=0x50, p=0x21, ram=[
            (0x0200, 0xE9), (0x0201, 0x30),
        ])
        cpu.step()
        assert cpu.A == 0x20
        assert cpu.V is False
        assert cpu.C is True

    def test_sbc_same_sign_borrow_no_overflow(self):
        """0x50 - 0x60 = 0xF0; same sign, wraps unsigned but no signed overflow"""
        cpu = make_cpu(FixedCPU, 0x0200, a=0x50, p=0x21, ram=[
            (0x0200, 0xE9), (0x0201, 0x60),
        ])
        cpu.step()
        assert cpu.A == 0xF0
        assert cpu.V is False, "SBC: same sign subtraction should not set V"
        assert cpu.C is False


# ============================================================
# Conformance database verification
# ============================================================
class TestConformanceDB:
    def test_db_exists(self):
        assert os.path.isfile('/app/conformance.db'), "conformance.db missing"

    def test_opcode_results_table_exists(self):
        conn = sqlite3.connect('/app/conformance.db')
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='opcode_results'")
        result = cur.fetchone()
        conn.close()
        assert result is not None, "Table opcode_results does not exist"

    def test_opcode_results_schema(self):
        conn = sqlite3.connect('/app/conformance.db')
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(opcode_results)")
        cols = {row[1] for row in cur.fetchall()}
        conn.close()
        required = {'opcode', 'mnemonic', 'addressing_mode', 'total_tests', 'passed', 'failed'}
        missing = required - cols
        assert not missing, f"opcode_results missing columns: {missing}"

    def test_opcode_results_sufficient_coverage(self):
        conn = sqlite3.connect('/app/conformance.db')
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM opcode_results")
        count = cur.fetchone()[0]
        conn.close()
        assert count >= 15, f"Must have >=15 opcode result rows, found {count}"

    def test_opcode_results_all_passing(self):
        conn = sqlite3.connect('/app/conformance.db')
        cur = conn.cursor()
        cur.execute("SELECT opcode, failed FROM opcode_results WHERE failed > 0")
        failures = cur.fetchall()
        conn.close()
        assert len(failures) == 0, f"Opcodes still failing after fix: {failures}"

    def test_opcode_results_mnemonic_populated(self):
        conn = sqlite3.connect('/app/conformance.db')
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM opcode_results WHERE mnemonic IS NULL OR mnemonic = ''")
        count = cur.fetchone()[0]
        conn.close()
        assert count == 0, "Some opcode_results rows have empty mnemonics"

    def test_opcode_results_addressing_mode_populated(self):
        conn = sqlite3.connect('/app/conformance.db')
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM opcode_results WHERE addressing_mode IS NULL OR addressing_mode = ''")
        count = cur.fetchone()[0]
        conn.close()
        assert count == 0, "Some opcode_results rows have empty addressing_mode"

    def test_bugs_table_exists(self):
        conn = sqlite3.connect('/app/conformance.db')
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bugs'")
        result = cur.fetchone()
        conn.close()
        assert result is not None, "Table bugs does not exist"

    def test_bugs_schema(self):
        conn = sqlite3.connect('/app/conformance.db')
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(bugs)")
        cols = {row[1] for row in cur.fetchall()}
        conn.close()
        required = {'id', 'severity', 'category', 'root_cause', 'affected_opcodes', 'fix_description'}
        missing = required - cols
        assert not missing, f"bugs table missing columns: {missing}"

    def test_bugs_count(self):
        conn = sqlite3.connect('/app/conformance.db')
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM bugs")
        count = cur.fetchone()[0]
        conn.close()
        assert count >= 7, f"Should identify >=7 bugs, found {count}"

    def test_bugs_severity_values(self):
        conn = sqlite3.connect('/app/conformance.db')
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT severity FROM bugs")
        severities = {row[0] for row in cur.fetchall()}
        conn.close()
        valid = {'critical', 'major', 'minor'}
        invalid = severities - valid
        assert not invalid, f"Invalid severity values: {invalid}"

    def test_bugs_diverse_categories(self):
        conn = sqlite3.connect('/app/conformance.db')
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT category FROM bugs")
        categories = {row[0] for row in cur.fetchall()}
        conn.close()
        assert len(categories) >= 3, (
            f"Expected >=3 distinct bug categories, got {categories}"
        )


# ============================================================
# Severity ranking verification
# ============================================================
class TestSeverityRanking:
    def test_ranking_exists(self):
        assert os.path.isfile('/app/bug_severity_ranking.json'), "bug_severity_ranking.json missing"

    def test_ranking_count(self):
        with open('/app/bug_severity_ranking.json') as f:
            ranking = json.load(f)
        assert isinstance(ranking, list)
        assert len(ranking) >= 7, f"Should rank >=7 bugs, found {len(ranking)}"

    def test_ranking_structure(self):
        with open('/app/bug_severity_ranking.json') as f:
            ranking = json.load(f)
        for entry in ranking:
            assert 'id' in entry, "Ranking entry missing 'id'"
            assert 'severity' in entry, f"Entry {entry.get('id')} missing 'severity'"
            assert entry['severity'] in ('critical', 'major', 'minor'), (
                f"Invalid severity: {entry['severity']}"
            )
            assert 'affected_opcode_count' in entry, (
                f"Entry {entry.get('id')} missing 'affected_opcode_count'"
            )
            assert isinstance(entry['affected_opcode_count'], int), (
                "affected_opcode_count must be int"
            )
            assert 'justification' in entry, f"Entry {entry.get('id')} missing 'justification'"
            assert len(entry['justification']) > 20, (
                f"Entry {entry['id']}: justification too short"
            )

    def test_ranking_sorted_by_severity(self):
        """Ranking must be sorted by decreasing severity."""
        with open('/app/bug_severity_ranking.json') as f:
            ranking = json.load(f)
        severity_order = {'critical': 3, 'major': 2, 'minor': 1}
        for i in range(len(ranking) - 1):
            current = severity_order.get(ranking[i]['severity'], 0)
            next_val = severity_order.get(ranking[i + 1]['severity'], 0)
            assert current >= next_val, (
                f"Ranking not sorted: bug {ranking[i]['id']} ({ranking[i]['severity']}) "
                f"before bug {ranking[i+1]['id']} ({ranking[i+1]['severity']})"
            )

    def test_ranking_multiple_severity_levels(self):
        with open('/app/bug_severity_ranking.json') as f:
            ranking = json.load(f)
        severities = {entry['severity'] for entry in ranking}
        assert len(severities) >= 2, f"Expected >=2 distinct severity levels, got {severities}"


# ============================================================
# Discriminating tests verification
# ============================================================
class TestDiscriminatingTests:
    def test_discriminating_tests_exist(self):
        assert os.path.isfile('/app/discriminating_tests.json'), (
            "discriminating_tests.json missing"
        )

    def test_discriminating_tests_count(self):
        with open('/app/discriminating_tests.json') as f:
            tests = json.load(f)
        assert isinstance(tests, list)
        assert len(tests) >= 7, f"Need >=7 discriminating tests, found {len(tests)}"

    def test_discriminating_tests_structure(self):
        with open('/app/discriminating_tests.json') as f:
            tests = json.load(f)
        for test in tests:
            assert 'name' in test, "Discriminating test missing 'name'"
            assert 'initial' in test, f"Test '{test.get('name')}' missing 'initial'"
            assert 'final' in test, f"Test '{test.get('name')}' missing 'final'"
            for key in ['pc', 's', 'a', 'x', 'y', 'p', 'ram']:
                assert key in test['initial'], (
                    f"Test '{test['name']}' missing initial.{key}"
                )

    def test_discriminating_tests_fail_on_original(self):
        """Each discriminating test must fail on the original buggy emulator."""
        with open('/app/discriminating_tests.json') as f:
            tests = json.load(f)
        fail_count = 0
        for test in tests:
            passed, errors = run_test_case(OriginalCPU, test)
            if not passed:
                fail_count += 1
        assert fail_count >= 7, (
            f"Only {fail_count}/{len(tests)} discriminating tests fail on original; "
            f"expected >=7"
        )

    def test_discriminating_tests_pass_on_fixed(self):
        """Each discriminating test must pass on the fixed emulator."""
        with open('/app/discriminating_tests.json') as f:
            tests = json.load(f)
        for test in tests:
            passed, errors = run_test_case(FixedCPU, test)
            assert passed, (
                f"Test '{test['name']}' fails on fixed emulator: {errors}"
            )


# ============================================================
# Patch file verification
# ============================================================
class TestPatchFile:
    def test_patch_exists(self):
        assert os.path.isfile('/app/emulator_changes.patch'), (
            "emulator_changes.patch missing"
        )

    def test_patch_nonempty(self):
        with open('/app/emulator_changes.patch') as f:
            content = f.read()
        assert len(content) > 50, "Patch file seems too short to contain real changes"

    def test_patch_is_unified_diff(self):
        with open('/app/emulator_changes.patch') as f:
            content = f.read()
        assert '---' in content and '+++' in content, (
            "Patch should be in unified diff format"
        )
        assert '@@' in content, "Patch should contain diff hunks"


# ============================================================
# Regression tests — correct instructions must stay correct
# ============================================================
class TestRegressions:
    def test_lda_immediate(self):
        cpu = make_cpu(FixedCPU, 0x0200, ram=[
            (0x0200, 0xA9), (0x0201, 0x42),
        ])
        cpu.step()
        assert cpu.A == 0x42
        assert cpu.PC == 0x0202

    def test_jmp_absolute(self):
        cpu = make_cpu(FixedCPU, 0x0300, ram=[
            (0x0300, 0x4C), (0x0301, 0x00), (0x0302, 0x80),
        ])
        cpu.step()
        assert cpu.PC == 0x8000

    def test_ror_a(self):
        cpu = make_cpu(FixedCPU, 0x0200, a=0x01, p=0x20, ram=[
            (0x0200, 0x6A),
        ])
        cpu.step()
        assert cpu.A == 0x00
        assert cpu.C is True
        assert cpu.Z is True

    def test_binary_adc_with_overflow(self):
        cpu = make_cpu(FixedCPU, 0x0200, a=0x7F, p=0x20, ram=[
            (0x0200, 0x69), (0x0201, 0x01),
        ])
        cpu.step()
        assert cpu.A == 0x80
        assert cpu.V is True
        assert cpu.N is True

    def test_binary_adc_no_overflow(self):
        cpu = make_cpu(FixedCPU, 0x0200, a=0x05, p=0x20, ram=[
            (0x0200, 0x69), (0x0201, 0x03),
        ])
        cpu.step()
        assert cpu.A == 0x08
        assert cpu.C is False

    def test_lda_zpx_no_wrap(self):
        cpu = make_cpu(FixedCPU, 0x0200, x=0x05, ram=[
            (0x0200, 0xB5), (0x0201, 0x10),
            (0x0015, 0x42),
        ])
        cpu.step()
        assert cpu.A == 0x42

    def test_izy_no_wrap(self):
        """Indirect indexed Y should still work after izx fix."""
        cpu = make_cpu(FixedCPU, 0x0200, y=0x05, ram=[
            (0x0200, 0xB1), (0x0201, 0x50),
            (0x0050, 0x00), (0x0051, 0x03),
            (0x0305, 0x77),
        ])
        cpu.step()
        assert cpu.A == 0x77
