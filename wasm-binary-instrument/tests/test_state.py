#!/usr/bin/env python3
"""Tests for WebAssembly binary profiling transformer.

Verifies that /app/wasm_profiler.py correctly transforms a WASM module to add
per-function counter globals, a synthesized reporter function, and a metadata
global — handling index space management across type, function, code, global,
and export sections.
"""


import os
import struct
import subprocess
import tempfile

import pytest


# ======================== LEB128 Helpers ========================

def decode_uleb128(data, offset):
    result = 0
    shift = 0
    while True:
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            break
        shift += 7
    return result, offset


def encode_uleb128(value):
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            byte |= 0x80
        result.append(byte)
        if not value:
            break
    return bytes(result)


def encode_sleb128(value):
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if (value == 0 and (byte & 0x40) == 0) or \
           (value == -1 and (byte & 0x40) != 0):
            result.append(byte)
            break
        else:
            result.append(byte | 0x80)
    return bytes(result)


def decode_sleb128(data, offset):
    result = 0
    shift = 0
    while True:
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        shift += 7
        if (byte & 0x80) == 0:
            break
    if shift < 64 and (byte & 0x40):
        result |= -(1 << shift)
    return result, offset


# ======================== WASM Parsing Helpers ========================

def parse_sections(data):
    """Parse WASM binary into list of (section_id, content_bytes)."""
    assert data[:4] == b'\x00asm', "Invalid WASM magic"
    assert struct.unpack('<I', data[4:8])[0] == 1, "Unexpected WASM version"
    offset = 8
    sections = []
    while offset < len(data):
        sid = data[offset]
        offset += 1
        size, offset = decode_uleb128(data, offset)
        content = data[offset:offset + size]
        sections.append((sid, bytes(content)))
        offset += size
    return sections


def get_section(sections, target_id):
    """Return the content of the first section matching target_id, or None."""
    for sid, content in sections:
        if sid == target_id:
            return content
    return None


def parse_export_entries(content):
    """Parse export section into list of (name, kind, index)."""
    offset = 0
    count, offset = decode_uleb128(content, offset)
    exports = []
    for _ in range(count):
        name_len, offset = decode_uleb128(content, offset)
        name = content[offset:offset + name_len].decode('utf-8')
        offset += name_len
        kind = content[offset]
        offset += 1
        index, offset = decode_uleb128(content, offset)
        exports.append((name, kind, index))
    return exports


def parse_code_bodies(content):
    """Parse code section into list of (locals_bytes, instruction_bytes)."""
    offset = 0
    func_count, offset = decode_uleb128(content, offset)
    bodies = []
    for _ in range(func_count):
        body_size, offset = decode_uleb128(content, offset)
        body_start = offset
        body_end = offset + body_size

        local_decl_count, pos = decode_uleb128(content, body_start)
        for _ in range(local_decl_count):
            _, pos = decode_uleb128(content, pos)  # run-length count
            pos += 1  # valtype

        locals_bytes = content[body_start:pos]
        instructions = content[pos:body_end]
        bodies.append((locals_bytes, instructions))
        offset = body_end
    return bodies


def parse_global_entries(content):
    """Parse global section into list of (valtype, mutability, init_value)."""
    offset = 0
    count, offset = decode_uleb128(content, offset)
    entries = []
    for _ in range(count):
        valtype = content[offset]; offset += 1
        mut = content[offset]; offset += 1
        opcode = content[offset]; offset += 1
        if opcode == 0x41:  # i32.const
            value, offset = decode_sleb128(content, offset)
        elif opcode == 0x42:  # i64.const
            value, offset = decode_sleb128(content, offset)
        elif opcode == 0x23:  # global.get
            _, offset = decode_uleb128(content, offset)
            value = None
        else:
            value = None
        assert content[offset] == 0x0B, f"Expected end opcode, got 0x{content[offset]:02X}"
        offset += 1
        entries.append((valtype, mut, value))
    return entries


def parse_type_section(content):
    """Parse type section into list of (params_list, results_list)."""
    offset = 0
    count, offset = decode_uleb128(content, offset)
    types = []
    for _ in range(count):
        assert content[offset] == 0x60, "Expected functype marker"
        offset += 1
        param_count, offset = decode_uleb128(content, offset)
        params = list(content[offset:offset + param_count])
        offset += param_count
        result_count, offset = decode_uleb128(content, offset)
        results = list(content[offset:offset + result_count])
        offset += result_count
        types.append((params, results))
    return types


def parse_function_section(content):
    """Parse function section into list of type indices."""
    offset = 0
    count, offset = decode_uleb128(content, offset)
    indices = []
    for _ in range(count):
        idx, offset = decode_uleb128(content, offset)
        indices.append(idx)
    return indices


def build_expected_prologue(global_idx):
    """Build the expected prologue byte sequence for a given global index."""
    code = bytearray()
    code.append(0x23)  # global.get
    code.extend(encode_uleb128(global_idx))
    code.append(0x41)  # i32.const
    code.extend(encode_sleb128(1))
    code.append(0x6A)  # i32.add
    code.append(0x24)  # global.set
    code.extend(encode_uleb128(global_idx))
    return bytes(code)


# ======================== WAT Test Modules ========================

# Single function, no globals, no imports
WAT_SIMPLE = """(module
  (func (export "add") (param i32 i32) (result i32)
    local.get 0
    local.get 1
    i32.add))"""

# Two functions, internal call
WAT_MULTI_FUNC = """(module
  (func (param i32) (result i32)
    local.get 0
    i32.const 2
    i32.mul)
  (func (export "compute") (param i32) (result i32)
    local.get 0
    call 0)
  (export "helper" (func 0)))"""

# Module with two existing defined globals
WAT_WITH_GLOBALS = """(module
  (global (mut i32) (i32.const 10))
  (global i32 (i32.const 20))
  (func (export "sum_globals") (result i32)
    global.get 0
    global.get 1
    i32.add))"""

# Module with an imported global
WAT_WITH_IMPORTED_GLOBAL = """(module
  (import "env" "base" (global i32))
  (global (mut i32) (i32.const 5))
  (func (export "compute") (result i32)
    global.get 0
    global.get 1
    i32.add))"""

# Function with local variable declarations
WAT_WITH_LOCALS = """(module
  (func (export "complex") (param i32) (result i32)
    (local i32 i32)
    local.get 0
    i32.const 3
    i32.mul
    local.set 1
    local.get 1
    i32.const 1
    i32.add
    local.set 2
    local.get 2))"""

# Void function with no instructions
WAT_NOOP = """(module
  (func (export "noop")))"""

# Completely empty module (no functions, globals, or exports)
WAT_MINIMAL = """(module)"""

# Complex module: function import, global import, defined global, multiple funcs
WAT_COMPLEX = """(module
  (import "env" "log" (func (param i32)))
  (import "env" "base_val" (global i32))
  (global (mut i32) (i32.const 0))
  (func (param i32 i32) (result i32)
    local.get 0
    local.get 1
    i32.add)
  (func (export "run") (param i32) (result i32)
    local.get 0
    i32.const 10
    call 1)
  (export "adder" (func 1))
  (export "my_counter" (global 1)))"""

# Module that already has a (i32)->(i32) type — tests type deduplication
WAT_TYPE_REUSE = """(module
  (type (func (param i32) (result i32)))
  (func (type 0) (param i32) (result i32)
    local.get 0
    i32.const 1
    i32.add)
  (export "inc" (func 0)))"""

# Module with imported function but no imported globals
WAT_IMPORTED_FUNC = """(module
  (import "env" "log" (func (param i32)))
  (func (export "do_log") (param i32)
    local.get 0
    call 0))"""


# ======================== Test Infrastructure ========================

def instrument(tmpdir, wat_source):
    """Compile WAT -> WASM, run wasm_profiler.py, return (input_bytes, output_bytes, output_path)."""
    wat_path = os.path.join(tmpdir, 'test.wat')
    input_path = os.path.join(tmpdir, 'input.wasm')
    output_path = os.path.join(tmpdir, 'output.wasm')

    with open(wat_path, 'w') as f:
        f.write(wat_source)

    r = subprocess.run(['wat2wasm', wat_path, '-o', input_path],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"wat2wasm failed: {r.stderr}"

    r = subprocess.run(['python3', '/app/wasm_profiler.py', input_path, output_path],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"wasm_profiler.py failed: {r.stderr}"

    with open(input_path, 'rb') as f:
        input_data = f.read()
    with open(output_path, 'rb') as f:
        output_data = f.read()
    return input_data, output_data, output_path


# ======================== Tests: WASM Validity ========================

class TestValidation:
    """Instrumented output must pass wasm-validate."""

    @pytest.mark.parametrize("wat,label", [
        (WAT_SIMPLE, "simple"),
        (WAT_MULTI_FUNC, "multi_func"),
        (WAT_WITH_GLOBALS, "with_globals"),
        (WAT_WITH_IMPORTED_GLOBAL, "with_imported_global"),
        (WAT_WITH_LOCALS, "with_locals"),
        (WAT_NOOP, "noop"),
        (WAT_MINIMAL, "minimal"),
        (WAT_COMPLEX, "complex"),
        (WAT_TYPE_REUSE, "type_reuse"),
        (WAT_IMPORTED_FUNC, "imported_func"),
    ])
    def test_output_passes_wasm_validate(self, tmp_path, wat, label):
        _, _, output_path = instrument(str(tmp_path), wat)
        r = subprocess.run(['wasm-validate', output_path],
                           capture_output=True, text=True)
        assert r.returncode == 0, \
            f"wasm-validate failed for '{label}': {r.stderr}"


# ======================== Tests: Global Section ========================

class TestGlobalSection:
    """Global section must contain original globals + N counters + __num_functions."""

    def test_count_simple(self, tmp_path):
        """1 func, no existing globals → 1 counter + 1 meta = 2."""
        _, out, _ = instrument(str(tmp_path), WAT_SIMPLE)
        gc = get_section(parse_sections(out), 6)
        count, _ = decode_uleb128(gc, 0)
        assert count == 2

    def test_count_multi_func(self, tmp_path):
        """2 funcs → 2 counters + 1 meta = 3."""
        _, out, _ = instrument(str(tmp_path), WAT_MULTI_FUNC)
        gc = get_section(parse_sections(out), 6)
        count, _ = decode_uleb128(gc, 0)
        assert count == 3

    def test_count_with_existing_globals(self, tmp_path):
        """2 existing globals + 1 func → 2 + 1 + 1 = 4."""
        _, out, _ = instrument(str(tmp_path), WAT_WITH_GLOBALS)
        gc = get_section(parse_sections(out), 6)
        count, _ = decode_uleb128(gc, 0)
        assert count == 4

    def test_count_with_imported_global(self, tmp_path):
        """1 imported + 1 defined + 1 func → section has 1 + 1 + 1 = 3 (imports not in section)."""
        _, out, _ = instrument(str(tmp_path), WAT_WITH_IMPORTED_GLOBAL)
        gc = get_section(parse_sections(out), 6)
        count, _ = decode_uleb128(gc, 0)
        assert count == 3

    def test_count_minimal(self, tmp_path):
        """No functions → 0 counters + 1 meta = 1."""
        _, out, _ = instrument(str(tmp_path), WAT_MINIMAL)
        gc = get_section(parse_sections(out), 6)
        assert gc is not None, "Global section must be created"
        count, _ = decode_uleb128(gc, 0)
        assert count == 1

    def test_counter_globals_are_mutable_i32_zero(self, tmp_path):
        """Counter globals must be mutable i32 initialized to 0."""
        _, out, _ = instrument(str(tmp_path), WAT_MULTI_FUNC)
        entries = parse_global_entries(get_section(parse_sections(out), 6))
        # First 2 entries are counters (no existing globals)
        for i in range(2):
            valtype, mut, value = entries[i]
            assert valtype == 0x7F, f"Counter {i} must be i32"
            assert mut == 0x01, f"Counter {i} must be mutable"
            assert value == 0, f"Counter {i} must init to 0"

    def test_counter_appended_after_existing(self, tmp_path):
        """With 2 existing globals, counters start at position 2."""
        _, out, _ = instrument(str(tmp_path), WAT_WITH_GLOBALS)
        entries = parse_global_entries(get_section(parse_sections(out), 6))
        # entries[0] and [1] are original globals
        # entries[2] is the counter
        assert entries[2][0] == 0x7F  # i32
        assert entries[2][1] == 0x01  # mutable
        assert entries[2][2] == 0     # init 0

    def test_num_functions_global_value(self, tmp_path):
        """__num_functions global must have correct init value."""
        _, out, _ = instrument(str(tmp_path), WAT_MULTI_FUNC)
        entries = parse_global_entries(get_section(parse_sections(out), 6))
        # Last entry is __num_functions
        last = entries[-1]
        assert last[0] == 0x7F, "__num_functions must be i32"
        assert last[1] == 0x00, "__num_functions must be immutable"
        assert last[2] == 2, f"Expected __num_functions=2, got {last[2]}"

    def test_num_functions_zero_for_empty(self, tmp_path):
        """Empty module: __num_functions = 0."""
        _, out, _ = instrument(str(tmp_path), WAT_MINIMAL)
        entries = parse_global_entries(get_section(parse_sections(out), 6))
        last = entries[-1]
        assert last[0] == 0x7F
        assert last[1] == 0x00
        assert last[2] == 0

    def test_num_functions_complex(self, tmp_path):
        """Complex module with 2 defined funcs: __num_functions = 2."""
        _, out, _ = instrument(str(tmp_path), WAT_COMPLEX)
        entries = parse_global_entries(get_section(parse_sections(out), 6))
        last = entries[-1]
        assert last[2] == 2


# ======================== Tests: Export Section ========================

class TestExportSection:
    """__get_call_count and __num_functions must be correctly exported."""

    def test_get_call_count_present(self, tmp_path):
        _, out, _ = instrument(str(tmp_path), WAT_SIMPLE)
        exports = parse_export_entries(get_section(parse_sections(out), 7))
        names = [e[0] for e in exports]
        assert '__get_call_count' in names

    def test_get_call_count_is_func(self, tmp_path):
        _, out, _ = instrument(str(tmp_path), WAT_SIMPLE)
        exports = parse_export_entries(get_section(parse_sections(out), 7))
        cc = next(e for e in exports if e[0] == '__get_call_count')
        assert cc[1] == 0x00, f"Expected func kind (0x00), got 0x{cc[1]:02X}"

    def test_get_call_count_index_simple(self, tmp_path):
        """No imports, 1 defined func → reporter at func index 1."""
        _, out, _ = instrument(str(tmp_path), WAT_SIMPLE)
        exports = parse_export_entries(get_section(parse_sections(out), 7))
        cc = next(e for e in exports if e[0] == '__get_call_count')
        assert cc[2] == 1

    def test_get_call_count_index_with_imports(self, tmp_path):
        """1 imported func + 2 defined → reporter at func index 3."""
        _, out, _ = instrument(str(tmp_path), WAT_COMPLEX)
        exports = parse_export_entries(get_section(parse_sections(out), 7))
        cc = next(e for e in exports if e[0] == '__get_call_count')
        assert cc[2] == 3

    def test_get_call_count_index_imported_func(self, tmp_path):
        """1 imported func + 1 defined → reporter at func index 2."""
        _, out, _ = instrument(str(tmp_path), WAT_IMPORTED_FUNC)
        exports = parse_export_entries(get_section(parse_sections(out), 7))
        cc = next(e for e in exports if e[0] == '__get_call_count')
        assert cc[2] == 2

    def test_num_functions_export_present(self, tmp_path):
        _, out, _ = instrument(str(tmp_path), WAT_SIMPLE)
        exports = parse_export_entries(get_section(parse_sections(out), 7))
        names = [e[0] for e in exports]
        assert '__num_functions' in names

    def test_num_functions_is_global(self, tmp_path):
        _, out, _ = instrument(str(tmp_path), WAT_SIMPLE)
        exports = parse_export_entries(get_section(parse_sections(out), 7))
        nf = next(e for e in exports if e[0] == '__num_functions')
        assert nf[1] == 0x03, f"Expected global kind (0x03), got 0x{nf[1]:02X}"

    def test_num_functions_index_simple(self, tmp_path):
        """No imports, no existing globals, 1 func → __num_functions at global 1."""
        _, out, _ = instrument(str(tmp_path), WAT_SIMPLE)
        exports = parse_export_entries(get_section(parse_sections(out), 7))
        nf = next(e for e in exports if e[0] == '__num_functions')
        assert nf[2] == 1

    def test_num_functions_index_with_imports(self, tmp_path):
        """1 imported global + 1 defined + 2 counters → __num_functions at global 4."""
        _, out, _ = instrument(str(tmp_path), WAT_COMPLEX)
        exports = parse_export_entries(get_section(parse_sections(out), 7))
        nf = next(e for e in exports if e[0] == '__num_functions')
        assert nf[2] == 4

    def test_existing_exports_preserved(self, tmp_path):
        _, out, _ = instrument(str(tmp_path), WAT_COMPLEX)
        exports = parse_export_entries(get_section(parse_sections(out), 7))
        names = [e[0] for e in exports]
        for expected_name in ['run', 'adder', 'my_counter']:
            assert expected_name in names, f"Missing original export: {expected_name}"

    def test_exports_created_for_minimal(self, tmp_path):
        """Empty module with no exports: export section must be created."""
        _, out, _ = instrument(str(tmp_path), WAT_MINIMAL)
        ec = get_section(parse_sections(out), 7)
        assert ec is not None, "Export section must be created"
        exports = parse_export_entries(ec)
        names = [e[0] for e in exports]
        assert '__get_call_count' in names
        assert '__num_functions' in names


# ======================== Tests: Code Section / Prologue ========================

class TestPrologue:
    """Each defined function must have the correct counter-increment prologue."""

    def test_single_function_prologue(self, tmp_path):
        """1 func, counter at global 0."""
        _, out, _ = instrument(str(tmp_path), WAT_SIMPLE)
        bodies = parse_code_bodies(get_section(parse_sections(out), 10))
        expected = build_expected_prologue(0)
        # First body is the original function (reporter is last)
        _, instr = bodies[0]
        assert instr[:len(expected)] == expected

    def test_multi_func_each_has_own_counter(self, tmp_path):
        """2 funcs: func 0 uses global 0, func 1 uses global 1."""
        _, out, _ = instrument(str(tmp_path), WAT_MULTI_FUNC)
        bodies = parse_code_bodies(get_section(parse_sections(out), 10))
        for i in range(2):
            expected = build_expected_prologue(i)
            _, instr = bodies[i]
            assert instr[:len(expected)] == expected, \
                f"Function {i} prologue uses wrong counter global"

    def test_prologue_accounts_for_existing_globals(self, tmp_path):
        """2 existing globals → counter at global index 2."""
        _, out, _ = instrument(str(tmp_path), WAT_WITH_GLOBALS)
        bodies = parse_code_bodies(get_section(parse_sections(out), 10))
        expected = build_expected_prologue(2)
        _, instr = bodies[0]
        assert instr[:len(expected)] == expected

    def test_prologue_accounts_for_imported_globals(self, tmp_path):
        """1 imported + 1 defined global → counter at global index 2."""
        _, out, _ = instrument(str(tmp_path), WAT_WITH_IMPORTED_GLOBAL)
        bodies = parse_code_bodies(get_section(parse_sections(out), 10))
        expected = build_expected_prologue(2)
        _, instr = bodies[0]
        assert instr[:len(expected)] == expected

    def test_prologue_after_locals(self, tmp_path):
        """Prologue follows local declarations, not precedes them."""
        _, out, _ = instrument(str(tmp_path), WAT_WITH_LOCALS)
        bodies = parse_code_bodies(get_section(parse_sections(out), 10))
        expected = build_expected_prologue(0)
        locals_bytes, instr = bodies[0]
        local_count, _ = decode_uleb128(locals_bytes, 0)
        assert local_count >= 1, "Must have local declarations"
        assert instr[:len(expected)] == expected

    def test_original_instructions_preserved(self, tmp_path):
        """After prologue, original function body must be intact."""
        inp, out, _ = instrument(str(tmp_path), WAT_SIMPLE)

        orig_bodies = parse_code_bodies(get_section(parse_sections(inp), 10))
        _, orig_instr = orig_bodies[0]

        new_bodies = parse_code_bodies(get_section(parse_sections(out), 10))
        _, new_instr = new_bodies[0]

        prologue = build_expected_prologue(0)
        assert new_instr[len(prologue):] == orig_instr

    def test_noop_function_gets_prologue(self, tmp_path):
        """Even empty function body gets the prologue."""
        _, out, _ = instrument(str(tmp_path), WAT_NOOP)
        bodies = parse_code_bodies(get_section(parse_sections(out), 10))
        expected = build_expected_prologue(0)
        _, instr = bodies[0]
        assert instr[:len(expected)] == expected
        assert instr[len(expected):] == bytes([0x0B])

    def test_complex_module_prologues(self, tmp_path):
        """Complex: 1 imported global + 1 defined → counters at 2, 3."""
        _, out, _ = instrument(str(tmp_path), WAT_COMPLEX)
        bodies = parse_code_bodies(get_section(parse_sections(out), 10))
        for i in range(2):
            expected = build_expected_prologue(2 + i)
            _, instr = bodies[i]
            assert instr[:len(expected)] == expected, \
                f"Complex func {i} prologue wrong"


# ======================== Tests: Reporter Function ========================

class TestReporter:
    """The synthesized __get_call_count function must be structurally correct."""

    def test_function_section_grows_by_one(self, tmp_path):
        """Function section count increases by 1 for the reporter."""
        inp, out, _ = instrument(str(tmp_path), WAT_MULTI_FUNC)
        orig_fs = get_section(parse_sections(inp), 3)
        new_fs = get_section(parse_sections(out), 3)
        orig_count, _ = decode_uleb128(orig_fs, 0)
        new_count, _ = decode_uleb128(new_fs, 0)
        assert new_count == orig_count + 1

    def test_code_section_grows_by_one(self, tmp_path):
        """Code section count increases by 1 for the reporter body."""
        inp, out, _ = instrument(str(tmp_path), WAT_MULTI_FUNC)
        orig_cs = get_section(parse_sections(inp), 10)
        new_cs = get_section(parse_sections(out), 10)
        orig_count, _ = decode_uleb128(orig_cs, 0)
        new_count, _ = decode_uleb128(new_cs, 0)
        assert new_count == orig_count + 1

    def test_reporter_type_is_i32_to_i32(self, tmp_path):
        """Reporter's type index must map to (i32) -> (i32)."""
        _, out, _ = instrument(str(tmp_path), WAT_SIMPLE)
        sections = parse_sections(out)
        func_indices = parse_function_section(get_section(sections, 3))
        reporter_type_idx = func_indices[-1]  # last entry
        types = parse_type_section(get_section(sections, 1))
        params, results = types[reporter_type_idx]
        assert params == [0x7F], f"Expected (i32) params, got {params}"
        assert results == [0x7F], f"Expected (i32) results, got {results}"

    def test_reporter_body_references_counter_globals(self, tmp_path):
        """Reporter body must contain global.get for each counter global."""
        _, out, _ = instrument(str(tmp_path), WAT_MULTI_FUNC)
        sections = parse_sections(out)
        bodies = parse_code_bodies(get_section(sections, 10))
        # Reporter is the last body
        _, reporter_instr = bodies[-1]
        # Counters at global indices 0 and 1
        for gidx in [0, 1]:
            pattern = bytes([0x23]) + encode_uleb128(gidx)
            assert pattern in reporter_instr, \
                f"Reporter body missing global.get {gidx}"

    def test_reporter_references_correct_globals_with_imports(self, tmp_path):
        """With imported global, counter globals start at higher index."""
        _, out, _ = instrument(str(tmp_path), WAT_COMPLEX)
        sections = parse_sections(out)
        bodies = parse_code_bodies(get_section(sections, 10))
        _, reporter_instr = bodies[-1]
        # 1 imported + 1 defined = counters at 2, 3
        for gidx in [2, 3]:
            pattern = bytes([0x23]) + encode_uleb128(gidx)
            assert pattern in reporter_instr, \
                f"Reporter body missing global.get {gidx}"

    def test_minimal_module_reporter_returns_zero(self, tmp_path):
        """Empty module: reporter has no global.get, just returns 0."""
        _, out, _ = instrument(str(tmp_path), WAT_MINIMAL)
        sections = parse_sections(out)
        bodies = parse_code_bodies(get_section(sections, 10))
        assert len(bodies) == 1, "Minimal module should have exactly 1 body (reporter)"
        _, reporter_instr = bodies[0]
        # Must not contain global.get (0x23) for counter — only has i32.const 0
        assert 0x41 in reporter_instr, "Reporter should use i32.const"
        assert reporter_instr[-1] == 0x0B, "Reporter must end with end opcode"

    def test_sections_created_for_minimal(self, tmp_path):
        """Minimal module: function and code sections must be created."""
        _, out, _ = instrument(str(tmp_path), WAT_MINIMAL)
        sections = parse_sections(out)
        assert get_section(sections, 1) is not None, "Type section must exist"
        assert get_section(sections, 3) is not None, "Function section must exist"
        assert get_section(sections, 10) is not None, "Code section must exist"


# ======================== Tests: Type Deduplication ========================

class TestTypeManagement:
    """Type section management: reuse existing types, add when needed."""

    def test_type_reused_when_exists(self, tmp_path):
        """Module with existing (i32)->(i32): type count must not increase."""
        inp, out, _ = instrument(str(tmp_path), WAT_TYPE_REUSE)
        orig_types = parse_type_section(get_section(parse_sections(inp), 1))
        new_types = parse_type_section(get_section(parse_sections(out), 1))
        assert len(new_types) == len(orig_types), \
            f"Type count changed from {len(orig_types)} to {len(new_types)} — dedup failed"

    def test_type_added_when_missing(self, tmp_path):
        """Module without (i32)->(i32): type count must increase by 1."""
        inp, out, _ = instrument(str(tmp_path), WAT_SIMPLE)
        orig_types = parse_type_section(get_section(parse_sections(inp), 1))
        new_types = parse_type_section(get_section(parse_sections(out), 1))
        assert len(new_types) == len(orig_types) + 1


# ======================== Tests: Section Ordering ========================

class TestSectionOrdering:
    def test_known_sections_in_order(self, tmp_path):
        """Known sections (id 1-12) must appear in increasing order."""
        _, out, _ = instrument(str(tmp_path), WAT_COMPLEX)
        sections = parse_sections(out)
        known_ids = [sid for sid, _ in sections if sid != 0]
        assert known_ids == sorted(known_ids), \
            f"Sections out of order: {known_ids}"

    def test_ordering_when_sections_created(self, tmp_path):
        """When multiple sections are created for minimal module, correct order."""
        _, out, _ = instrument(str(tmp_path), WAT_MINIMAL)
        sections = parse_sections(out)
        known_ids = [sid for sid, _ in sections if sid != 0]
        assert known_ids == sorted(known_ids), \
            f"Sections out of order: {known_ids}"

    def test_ordering_with_imports(self, tmp_path):
        _, out, _ = instrument(str(tmp_path), WAT_IMPORTED_FUNC)
        sections = parse_sections(out)
        known_ids = [sid for sid, _ in sections if sid != 0]
        assert known_ids == sorted(known_ids)


# ======================== Tests: Decompilation Sanity ========================

class TestDecompilation:
    def test_wasm2wat_shows_get_call_count(self, tmp_path):
        """wasm2wat output should mention __get_call_count and global instructions."""
        _, _, output_path = instrument(str(tmp_path), WAT_SIMPLE)
        r = subprocess.run(['wasm2wat', output_path],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"wasm2wat failed: {r.stderr}"
        assert '__get_call_count' in r.stdout
        assert '__num_functions' in r.stdout
        assert 'global.get' in r.stdout
        assert 'global.set' in r.stdout

    def test_wasm2wat_complex_structure(self, tmp_path):
        """Complex module decompilation has all expected elements."""
        _, _, output_path = instrument(str(tmp_path), WAT_COMPLEX)
        r = subprocess.run(['wasm2wat', output_path],
                           capture_output=True, text=True)
        assert r.returncode == 0
        for token in ['__get_call_count', '__num_functions', 'run', 'adder']:
            assert token in r.stdout, f"Missing '{token}' in decompiled output"
