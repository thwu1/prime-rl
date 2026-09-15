"""
Tests for the DWARF .debug_frame CFI decoder.

Verifies the decoder produces correct CIE/FDE output including register
rule tables, using handcrafted .debug_frame sections with known expected
results.

"""

import os
import re
import struct
import subprocess
import pytest

WORK_DIR = "/app"
DECODER = os.path.join(WORK_DIR, "dwarf_cfi")


# ─── LEB128 helpers ───────────────────────────────────────────────

def uleb128(value):
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        if value != 0:
            b |= 0x80
        out.append(b)
        if value == 0:
            break
    return bytes(out)


def sleb128(value):
    out = bytearray()
    more = True
    while more:
        b = value & 0x7F
        value >>= 7
        if (value == 0 and (b & 0x40) == 0) or \
           (value == -1 and (b & 0x40) != 0):
            more = False
        else:
            b |= 0x80
        out.append(b)
    return bytes(out)


# ─── CFI instruction builders ─────────────────────────────────────

def cfa_nop():
    return b'\x00'

def cfa_def_cfa(reg, offset):
    return b'\x0c' + uleb128(reg) + uleb128(offset)

def cfa_def_cfa_offset(offset):
    return b'\x0e' + uleb128(offset)

def cfa_def_cfa_register(reg):
    return b'\x0d' + uleb128(reg)

def cfa_def_cfa_sf(reg, factored_offset):
    """DW_CFA_def_cfa_sf: signed factored CFA definition."""
    return b'\x12' + uleb128(reg) + sleb128(factored_offset)

def cfa_offset(reg, factored_offset):
    """DW_CFA_offset with register encoded in high-2-bit form (reg < 64)."""
    assert 0 <= reg < 64
    return bytes([0x80 | reg]) + uleb128(factored_offset)

def cfa_offset_extended(reg, factored_offset):
    return b'\x05' + uleb128(reg) + uleb128(factored_offset)

def cfa_offset_extended_sf(reg, factored_offset):
    """DW_CFA_offset_extended_sf: signed factored register offset."""
    return b'\x11' + uleb128(reg) + sleb128(factored_offset)

def cfa_val_offset(reg, factored_offset):
    """DW_CFA_val_offset: unsigned factored val_offset rule."""
    return b'\x14' + uleb128(reg) + uleb128(factored_offset)

def cfa_advance_loc(delta):
    """DW_CFA_advance_loc with delta in low 6 bits (delta < 64)."""
    assert 0 <= delta < 64
    return bytes([0x40 | delta])

def cfa_advance_loc1(delta):
    return b'\x02' + bytes([delta & 0xFF])

def cfa_advance_loc2(delta):
    return b'\x03' + struct.pack("<H", delta)

def cfa_remember_state():
    return b'\x0a'

def cfa_restore_state():
    return b'\x0b'

def cfa_same_value(reg):
    return b'\x08' + uleb128(reg)

def cfa_undefined(reg):
    return b'\x07' + uleb128(reg)

def cfa_register(reg, target):
    return b'\x09' + uleb128(reg) + uleb128(target)


# ─── Section builders ─────────────────────────────────────────────

def build_cie(version=4, code_align=1, data_align=1, return_reg=16,
              augmentation="", aug_data=b"", initial_instructions=b"",
              address_size=8):
    """Build a CIE in .debug_frame format (32-bit DWARF)."""
    body = bytearray()
    body.append(version)
    body.extend(augmentation.encode('ascii') + b'\x00')
    if version >= 4:
        body.append(address_size)
        body.append(0)  # segment_selector_size
    body.extend(uleb128(code_align))
    body.extend(sleb128(data_align))
    if version == 1:
        body.append(return_reg & 0xFF)
    else:
        body.extend(uleb128(return_reg))
    if augmentation.startswith('z'):
        body.extend(uleb128(len(aug_data)))
        body.extend(aug_data)
    body.extend(initial_instructions)

    cie_id = struct.pack("<I", 0xFFFFFFFF)
    content = cie_id + bytes(body)
    return struct.pack("<I", len(content)) + content


def build_fde(cie_offset, initial_location, address_range,
              instructions=b"", cie_has_z=False, aug_data=b"",
              address_size=8):
    """Build an FDE in .debug_frame format (32-bit DWARF)."""
    body = bytearray()
    body.extend(struct.pack("<I", cie_offset))
    if address_size == 4:
        body.extend(struct.pack("<I", initial_location))
        body.extend(struct.pack("<I", address_range))
    else:
        body.extend(struct.pack("<Q", initial_location))
        body.extend(struct.pack("<Q", address_range))
    if cie_has_z:
        body.extend(uleb128(len(aug_data)))
        body.extend(aug_data)
    body.extend(instructions)

    return struct.pack("<I", len(body)) + bytes(body)


def build_cie_64(version=4, code_align=1, data_align=1, return_reg=16,
                 augmentation="", aug_data=b"", initial_instructions=b"",
                 address_size=8):
    """Build a CIE in .debug_frame format (64-bit DWARF)."""
    body = bytearray()
    body.append(version)
    body.extend(augmentation.encode('ascii') + b'\x00')
    if version >= 4:
        body.append(address_size)
        body.append(0)  # segment_selector_size
    body.extend(uleb128(code_align))
    body.extend(sleb128(data_align))
    if version == 1:
        body.append(return_reg & 0xFF)
    else:
        body.extend(uleb128(return_reg))
    if augmentation.startswith('z'):
        body.extend(uleb128(len(aug_data)))
        body.extend(aug_data)
    body.extend(initial_instructions)

    # 64-bit DWARF CIE_id is 8-byte all-ones
    cie_id = struct.pack("<Q", 0xFFFFFFFFFFFFFFFF)
    content = cie_id + bytes(body)
    # 64-bit format: 0xFFFFFFFF marker + 8-byte length
    return struct.pack("<I", 0xFFFFFFFF) + struct.pack("<Q", len(content)) + content


def build_fde_64(cie_offset, initial_location, address_range,
                 instructions=b"", cie_has_z=False, aug_data=b"",
                 address_size=8):
    """Build an FDE in .debug_frame format (64-bit DWARF)."""
    body = bytearray()
    # 64-bit CIE pointer (8 bytes)
    body.extend(struct.pack("<Q", cie_offset))
    if address_size == 4:
        body.extend(struct.pack("<I", initial_location))
        body.extend(struct.pack("<I", address_range))
    else:
        body.extend(struct.pack("<Q", initial_location))
        body.extend(struct.pack("<Q", address_range))
    if cie_has_z:
        body.extend(uleb128(len(aug_data)))
        body.extend(aug_data)
    body.extend(instructions)

    return struct.pack("<I", 0xFFFFFFFF) + struct.pack("<Q", len(body)) + bytes(body)


# ─── Output parser ────────────────────────────────────────────────

def parse_output(text):
    """Parse decoder output into a list of CIE/FDE dicts with rule rows."""
    entries = []
    current = None

    for line in text.strip().splitlines():
        line = line.rstrip()

        cie_m = re.match(
            r'CIE @0x([0-9a-fA-F]+): v=(\d+) ca=(\d+) da=(-?\d+) '
            r'ret=(\d+) aug="([^"]*)"', line)
        if cie_m:
            current = {
                "type": "CIE",
                "offset": int(cie_m.group(1), 16),
                "version": int(cie_m.group(2)),
                "code_align": int(cie_m.group(3)),
                "data_align": int(cie_m.group(4)),
                "return_reg": int(cie_m.group(5)),
                "augmentation": cie_m.group(6),
                "rows": [],
            }
            entries.append(current)
            continue

        fde_m = re.match(
            r'FDE @0x([0-9a-fA-F]+): pc=\[0x([0-9a-fA-F]+),'
            r'0x([0-9a-fA-F]+)\) cie=@0x([0-9a-fA-F]+)', line)
        if fde_m:
            current = {
                "type": "FDE",
                "offset": int(fde_m.group(1), 16),
                "pc_begin": int(fde_m.group(2), 16),
                "pc_end": int(fde_m.group(3), 16),
                "cie_offset": int(fde_m.group(4), 16),
                "rows": [],
            }
            entries.append(current)
            continue

        row_m = re.match(r'\s+\[(\w+)\]\s+cfa=(.+)', line)
        if row_m and current is not None:
            loc_str = row_m.group(1)
            rest = row_m.group(2)

            loc = loc_str if loc_str == "initial" else int(loc_str, 16)

            # parse CFA
            cfa_m = re.match(r'r(\d+)([+-]\d+)', rest)
            cfa_reg = int(cfa_m.group(1)) if cfa_m else 0
            cfa_off = int(cfa_m.group(2)) if cfa_m else 0

            # parse register rules
            regs = {}
            brace_m = re.search(r'\{(.+)\}', rest)
            if brace_m:
                rules_str = brace_m.group(1)
                for rm in re.finditer(
                        r'r(\d+)=\[cfa([+-]\d+)\]', rules_str):
                    regs[int(rm.group(1))] = ("offset", int(rm.group(2)))
                for rm in re.finditer(
                        r'r(\d+)=val\(cfa([+-]\d+)\)', rules_str):
                    regs[int(rm.group(1))] = ("val_offset", int(rm.group(2)))
                for rm in re.finditer(r'r(\d+)=same', rules_str):
                    regs[int(rm.group(1))] = ("same", 0)
                for rm in re.finditer(r'r(\d+)=r(\d+)', rules_str):
                    regs[int(rm.group(1))] = ("register", int(rm.group(2)))

            current["rows"].append({
                "loc": loc,
                "cfa_reg": cfa_reg,
                "cfa_off": cfa_off,
                "regs": regs,
            })

    return entries


# ─── Helpers ──────────────────────────────────────────────────────

def _compile():
    r = subprocess.run(["make", "-C", WORK_DIR, "clean", "dwarf_cfi"],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"Build failed:\n{r.stderr}"


def _run(section_path, addr_size=8):
    r = subprocess.run([DECODER, section_path, str(addr_size)],
                       capture_output=True, text=True, timeout=15)
    assert r.returncode == 0, \
        f"Decoder exited with {r.returncode}:\n{r.stderr}\n{r.stdout}"
    return parse_output(r.stdout)


def _write_section(tmp_path, name, data):
    path = str(tmp_path / name)
    with open(path, "wb") as f:
        f.write(data)
    return path


# ─── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def build_decoder():
    _compile()


# ─── Tests ────────────────────────────────────────────────────────

class TestCIEParsing:
    """Verify CIE header fields are parsed correctly."""

    def test_basic_cie_fields(self, tmp_path):
        """CIE with positive data_align, verify all header fields."""
        cie = build_cie(version=4, code_align=2, data_align=3,
                        return_reg=16, augmentation="",
                        initial_instructions=cfa_def_cfa(7, 8))
        path = _write_section(tmp_path, "basic.bin", cie)
        entries = _run(path)
        assert len(entries) >= 1
        c = entries[0]
        assert c["type"] == "CIE"
        assert c["version"] == 4
        assert c["code_align"] == 2
        assert c["data_align"] == 3
        assert c["return_reg"] == 16

    def test_sleb128_negative_data_alignment(self, tmp_path):
        """CIE with data_alignment_factor = -8.

        SLEB128 encoding of -8 is 0x78. Correct decoding requires
        checking bit 6 (the sign bit in LEB128) for sign extension,
        not bit 7 (the continuation flag, which is always 0 on the
        last byte).
        """
        cie = build_cie(version=4, code_align=1, data_align=-8,
                        return_reg=16,
                        initial_instructions=cfa_def_cfa(7, 8))
        path = _write_section(tmp_path, "sleb.bin", cie)
        entries = _run(path)
        c = entries[0]
        assert c["data_align"] == -8, \
            f"SLEB128 sign extension bug: da should be -8, got {c['data_align']}"


class TestCIEInitialRules:
    """Verify CIE initial instructions produce correct rule rows."""

    def test_initial_rules_in_cie_output(self, tmp_path):
        """CIE initial instructions should be shown in [initial] row."""
        init_instr = cfa_def_cfa(7, 8) + cfa_offset(16, 1)
        cie = build_cie(version=4, code_align=1, data_align=1,
                        return_reg=16,
                        initial_instructions=init_instr)
        path = _write_section(tmp_path, "init.bin", cie)
        entries = _run(path)

        c = entries[0]
        init_rows = [r for r in c["rows"] if r["loc"] == "initial"]
        assert len(init_rows) == 1, "Missing [initial] row in CIE output"
        ir = init_rows[0]
        assert ir["cfa_reg"] == 7, f"CFA reg: expected 7, got {ir['cfa_reg']}"
        assert ir["cfa_off"] == 8, f"CFA off: expected 8, got {ir['cfa_off']}"
        assert 16 in ir["regs"], "r16 missing from initial rules"
        assert ir["regs"][16] == ("offset", 1), \
            f"r16: expected offset +1, got {ir['regs'][16]}"

    def test_fde_inherits_cie_initial_rules(self, tmp_path):
        """FDE's first rule row must inherit CIE initial rules.

        The DWARF spec requires that each FDE's rule table starts
        from the CIE's initial_instructions state before executing
        the FDE's own instructions.
        """
        init_instr = cfa_def_cfa(7, 8)
        cie = build_cie(version=4, code_align=1, data_align=1,
                        return_reg=16,
                        initial_instructions=init_instr)
        fde = build_fde(cie_offset=0, initial_location=0x1000,
                        address_range=0x40, instructions=b"")

        path = _write_section(tmp_path, "inherit.bin", cie + fde)
        entries = _run(path)

        fdes = [e for e in entries if e["type"] == "FDE"]
        assert len(fdes) == 1
        fde_rows = fdes[0]["rows"]
        assert len(fde_rows) >= 1, "FDE should have at least one rule row"
        r0 = fde_rows[0]
        assert r0["cfa_reg"] == 7, \
            f"FDE initial CFA reg: expected 7 (from CIE), got {r0['cfa_reg']}"
        assert r0["cfa_off"] == 8, \
            f"FDE initial CFA off: expected 8 (from CIE), got {r0['cfa_off']}"


class TestOffsetFactoring:
    """Verify DW_CFA_offset uses data_alignment_factor (not code)."""

    def test_offset_uses_data_align(self, tmp_path):
        """DW_CFA_offset factored_offset must be multiplied by
        data_alignment_factor, not code_alignment_factor.

        Uses code_align=3, data_align=5 (both positive, distinct).
        DW_CFA_offset r10, 4 -> offset should be 4*5=20, not 4*3=12.
        An advance_loc is needed after the offset to emit a row with
        the r10 rule in the output.
        """
        cie = build_cie(version=4, code_align=3, data_align=5,
                        return_reg=16,
                        initial_instructions=b"")
        fde_instr = (cfa_def_cfa(1, 16)
                     + cfa_offset(10, 4)
                     + cfa_advance_loc(1))
        fde = build_fde(cie_offset=0, initial_location=0x2000,
                        address_range=0x20, instructions=fde_instr)

        path = _write_section(tmp_path, "factor.bin", cie + fde)
        entries = _run(path)

        fdes = [e for e in entries if e["type"] == "FDE"]
        assert len(fdes) == 1
        # Find a row with r10 set
        r10_found = False
        for row in fdes[0]["rows"]:
            if 10 in row["regs"]:
                r10_found = True
                assert row["regs"][10] == ("offset", 20), \
                    f"r10 offset: expected 20 (4*data_align=5), " \
                    f"got {row['regs'][10]}"
                break
        assert r10_found, "r10 rule not found in FDE output"


class TestAdvanceLocFactoring:
    """Verify DW_CFA_advance_loc multiplies delta by code_alignment_factor."""

    def test_advance_loc_uses_code_align(self, tmp_path):
        """DW_CFA_advance_loc delta must be multiplied by
        code_alignment_factor.

        Uses code_align=4. DW_CFA_advance_loc 3 from 0x1000
        should advance to 0x1000 + 3*4 = 0x100c, not 0x1003.
        """
        cie = build_cie(version=4, code_align=4, data_align=1,
                        return_reg=16,
                        initial_instructions=b"")
        fde_instr = (cfa_def_cfa(7, 8)
                     + cfa_advance_loc(3)
                     + cfa_def_cfa_offset(16))
        fde = build_fde(cie_offset=0, initial_location=0x1000,
                        address_range=0x40, instructions=fde_instr)

        path = _write_section(tmp_path, "advloc.bin", cie + fde)
        entries = _run(path)

        fdes = [e for e in entries if e["type"] == "FDE"]
        assert len(fdes) == 1
        locs = [r["loc"] for r in fdes[0]["rows"]
                if isinstance(r["loc"], int) and r["loc"] > 0x1000]
        assert 0x100c in locs, \
            f"advance_loc(3) with code_align=4 should reach 0x100c; " \
            f"got locations {[hex(l) for l in locs]}"

    def test_advance_loc1_uses_code_align(self, tmp_path):
        """DW_CFA_advance_loc1 also multiplies by code_alignment_factor."""
        cie = build_cie(version=4, code_align=4, data_align=1,
                        return_reg=16,
                        initial_instructions=b"")
        fde_instr = (cfa_def_cfa(7, 8)
                     + cfa_advance_loc1(10)
                     + cfa_def_cfa_offset(16))
        fde = build_fde(cie_offset=0, initial_location=0x2000,
                        address_range=0x100, instructions=fde_instr)

        path = _write_section(tmp_path, "advloc1.bin", cie + fde)
        entries = _run(path)

        fdes = [e for e in entries if e["type"] == "FDE"]
        locs = [r["loc"] for r in fdes[0]["rows"]
                if isinstance(r["loc"], int) and r["loc"] > 0x2000]
        assert 0x2028 in locs, \
            f"advance_loc1(10) with code_align=4 should reach 0x2028; " \
            f"got {[hex(l) for l in locs]}"


class TestAugmentationZ:
    """Verify 'z' augmentation data is properly skipped in CIE parsing."""

    def test_augmentation_z_data_skipped(self, tmp_path):
        """When augmentation starts with 'z', the CIE contains
        augmentation_data_length followed by that many bytes of data.
        These bytes must be skipped before reading initial_instructions.

        The augmentation data bytes [0x85, 0x03, 0x00] look like
        DW_CFA_offset r5 3 + DW_CFA_nop. If not skipped, r5 will
        spuriously appear in the initial rules.
        """
        aug_data = bytes([0x85, 0x03, 0x00])  # looks like offset r5, 3 + nop
        init_instr = cfa_def_cfa(7, 8)
        cie = build_cie(version=4, code_align=1, data_align=1,
                        return_reg=16, augmentation="zR",
                        aug_data=aug_data,
                        initial_instructions=init_instr)
        fde = build_fde(cie_offset=0, initial_location=0x3000,
                        address_range=0x20, cie_has_z=True,
                        instructions=b"")

        path = _write_section(tmp_path, "augz.bin", cie + fde)
        entries = _run(path)

        cies = [e for e in entries if e["type"] == "CIE"]
        assert len(cies) >= 1
        init_rows = [r for r in cies[0]["rows"] if r["loc"] == "initial"]
        assert len(init_rows) == 1

        ir = init_rows[0]
        assert ir["cfa_reg"] == 7, \
            f"CFA reg should be 7 from real initial_instructions, got {ir['cfa_reg']}"
        assert ir["cfa_off"] == 8
        assert 5 not in ir["regs"], \
            "r5 should NOT appear in initial rules (augmentation data was " \
            "not skipped and was misinterpreted as DW_CFA_offset r5)"


class TestRememberRestore:
    """Verify DW_CFA_remember_state/restore_state uses LIFO semantics."""

    def test_remember_restore_is_lifo(self, tmp_path):
        """Push state A (r10=[cfa+1]), modify to B (r10=[cfa+2]),
        push B, modify to C (r10=[cfa+3]).
        First restore_state should give B (r10=[cfa+2]), not A.
        Second restore should give A (r10=[cfa+1]).
        """
        cie = build_cie(version=4, code_align=1, data_align=1,
                        return_reg=16,
                        initial_instructions=b"")
        fde_instr = (
            cfa_def_cfa(7, 8)
            + cfa_offset(10, 1)           # r10=[cfa+1] = state A
            + cfa_remember_state()        # push A
            + cfa_offset(10, 2)           # r10=[cfa+2] = state B
            + cfa_remember_state()        # push B
            + cfa_offset(10, 3)           # r10=[cfa+3] = state C
            + cfa_advance_loc(1)          # loc += 1, print C
            + cfa_restore_state()         # should restore B (LIFO)
            + cfa_advance_loc(1)          # loc += 1, print restored state
            + cfa_restore_state()         # should restore A (LIFO)
            + cfa_advance_loc(1)          # loc += 1, print restored state
        )
        fde = build_fde(cie_offset=0, initial_location=0x5000,
                        address_range=0x10, instructions=fde_instr)

        path = _write_section(tmp_path, "lifo.bin", cie + fde)
        entries = _run(path)

        fdes = [e for e in entries if e["type"] == "FDE"]
        assert len(fdes) == 1
        rows = fdes[0]["rows"]

        # Find rows by location
        row_map = {}
        for r in rows:
            if isinstance(r["loc"], int):
                row_map[r["loc"]] = r

        # At 0x5001: state C (r10=[cfa+3])
        assert 0x5001 in row_map, "Missing row at 0x5001"
        assert row_map[0x5001]["regs"].get(10) == ("offset", 3), \
            f"At 0x5001 (before restore): r10 should be [cfa+3], " \
            f"got {row_map[0x5001]['regs'].get(10)}"

        # At 0x5002: after first restore -> should be B (r10=[cfa+2])
        assert 0x5002 in row_map, "Missing row at 0x5002"
        assert row_map[0x5002]["regs"].get(10) == ("offset", 2), \
            f"After first restore (LIFO -> state B): r10 should be [cfa+2], " \
            f"got {row_map[0x5002]['regs'].get(10)}"

        # At 0x5003: after second restore -> should be A (r10=[cfa+1])
        assert 0x5003 in row_map, "Missing row at 0x5003"
        assert row_map[0x5003]["regs"].get(10) == ("offset", 1), \
            f"After second restore (LIFO -> state A): r10 should be [cfa+1], " \
            f"got {row_map[0x5003]['regs'].get(10)}"


class TestCombined:
    """End-to-end test with realistic x86-64-like CFI data."""

    def test_x86_64_scenario(self, tmp_path):
        """Simulate typical x86-64 CFI:
        CIE: code_align=1, data_align=-8, ret=16
             initial: def_cfa r7 8, offset r16 1
        FDE: def_cfa_offset 16, advance_loc 4,
             offset r6 2, advance_loc 8

        Correct output requires fixing ALL interacting bugs:
        - SLEB128 sign extension for da=-8
        - CIE initial rules applied to FDE
        - DW_CFA_offset uses data_alignment_factor
        - DW_CFA_advance_loc factored by code_alignment_factor
        """
        init_instr = cfa_def_cfa(7, 8) + cfa_offset(16, 1)
        cie = build_cie(version=4, code_align=1, data_align=-8,
                        return_reg=16,
                        initial_instructions=init_instr)

        fde_instr = (
            cfa_def_cfa_offset(16)
            + cfa_offset(6, 2)
            + cfa_advance_loc(4)
            + cfa_def_cfa_offset(8)
            + cfa_advance_loc(8)
        )
        fde = build_fde(cie_offset=0, initial_location=0x401000,
                        address_range=0x40, instructions=fde_instr)

        path = _write_section(tmp_path, "x86.bin", cie + fde)
        entries = _run(path)

        # Verify CIE
        cies = [e for e in entries if e["type"] == "CIE"]
        assert len(cies) == 1
        assert cies[0]["data_align"] == -8, \
            f"CIE da should be -8, got {cies[0]['data_align']}"

        # Verify CIE initial rules
        init_rows = [r for r in cies[0]["rows"] if r["loc"] == "initial"]
        assert len(init_rows) == 1
        ir = init_rows[0]
        assert ir["cfa_reg"] == 7 and ir["cfa_off"] == 8
        assert ir["regs"].get(16) == ("offset", -8), \
            f"CIE initial r16: expected [cfa-8], got {ir['regs'].get(16)}"

        # Verify FDE
        fdes = [e for e in entries if e["type"] == "FDE"]
        assert len(fdes) == 1
        assert fdes[0]["pc_begin"] == 0x401000
        assert fdes[0]["pc_end"] == 0x401040

        rows = fdes[0]["rows"]
        row_map = {}
        for r in rows:
            if isinstance(r["loc"], int):
                row_map[r["loc"]] = r

        # Initial row: inherits CIE rules, then def_cfa_offset 16 and offset r6 2
        # are applied before first advance_loc
        assert 0x401000 in row_map, "Missing initial FDE row"
        r0 = row_map[0x401000]
        # FDE starts with CIE initial rules (cfa=r7+8, r16=[cfa-8])
        # Then def_cfa_offset 16 and offset r6 2 happen but are not emitted
        # until advance_loc triggers the next row.
        # The initial print shows the state right when FDE starts (CIE defaults).
        assert r0["cfa_reg"] == 7, \
            f"FDE initial CFA reg: expected 7, got {r0['cfa_reg']}"
        assert r0["cfa_off"] == 8, \
            f"FDE initial CFA off: expected 8, got {r0['cfa_off']}"
        assert r0["regs"].get(16) == ("offset", -8), \
            f"FDE initial r16: expected [cfa-8], got {r0['regs'].get(16)}"

        # After advance_loc 4: loc=0x401004
        # Rules at this point: cfa=r7+16, r16=[cfa-8], r6=[cfa-16]
        assert 0x401004 in row_map, "Missing row at 0x401004"
        r1 = row_map[0x401004]
        assert r1["cfa_reg"] == 7
        assert r1["cfa_off"] == 16, \
            f"At 0x401004: CFA off expected 16, got {r1['cfa_off']}"
        assert r1["regs"].get(16) == ("offset", -8)
        assert r1["regs"].get(6) == ("offset", -16), \
            f"At 0x401004: r6 expected [cfa-16], got {r1['regs'].get(6)}"

        # After advance_loc 8: loc=0x40100c
        # Rules: cfa=r7+8 (def_cfa_offset 8), r16=[cfa-8], r6=[cfa-16]
        assert 0x40100c in row_map, "Missing row at 0x40100c"
        r2 = row_map[0x40100c]
        assert r2["cfa_off"] == 8, \
            f"At 0x40100c: CFA off expected 8, got {r2['cfa_off']}"

    def test_multi_fde_sequence(self, tmp_path):
        """Multiple FDEs referencing the same CIE."""
        init_instr = cfa_def_cfa(7, 8) + cfa_offset(16, 1)
        cie = build_cie(version=4, code_align=1, data_align=1,
                        return_reg=16,
                        initial_instructions=init_instr)

        fde1 = build_fde(cie_offset=0, initial_location=0xA000,
                         address_range=0x20,
                         instructions=cfa_advance_loc(4) + cfa_def_cfa_offset(16))
        fde2 = build_fde(cie_offset=0, initial_location=0xB000,
                         address_range=0x30,
                         instructions=cfa_advance_loc(8) + cfa_offset(6, 2))

        path = _write_section(tmp_path, "multi.bin", cie + fde1 + fde2)
        entries = _run(path)

        fdes = [e for e in entries if e["type"] == "FDE"]
        assert len(fdes) == 2, f"Expected 2 FDEs, got {len(fdes)}"
        assert fdes[0]["pc_begin"] == 0xA000
        assert fdes[1]["pc_begin"] == 0xB000

        # Both FDEs should inherit CIE initial rules
        for fde_entry in fdes:
            r0 = fde_entry["rows"][0]
            assert r0["cfa_reg"] == 7, \
                f"FDE @{hex(fde_entry['pc_begin'])} initial CFA reg " \
                f"should be 7, got {r0['cfa_reg']}"
            assert r0["cfa_off"] == 8


class TestEdgeCases:
    """Test edge cases and less common CFI instructions."""

    def test_cie_version_1_return_reg(self, tmp_path):
        """CIE version 1 uses single-byte return_address_register."""
        cie = build_cie(version=1, code_align=1, data_align=1,
                        return_reg=16,
                        initial_instructions=cfa_def_cfa(7, 8))
        path = _write_section(tmp_path, "v1.bin", cie)
        entries = _run(path)
        assert entries[0]["return_reg"] == 16

    def test_register_rule(self, tmp_path):
        """DW_CFA_register sets a register-to-register rule.
        An advance_loc is needed after the register instruction
        to emit a row with the register rule in the output.
        """
        cie = build_cie(version=4, code_align=1, data_align=1,
                        return_reg=16,
                        initial_instructions=b"")
        fde_instr = (cfa_def_cfa(7, 8)
                     + cfa_register(16, 6)
                     + cfa_advance_loc(1))
        fde = build_fde(cie_offset=0, initial_location=0x6000,
                        address_range=0x20, instructions=fde_instr)

        path = _write_section(tmp_path, "regrule.bin", cie + fde)
        entries = _run(path)

        fdes = [e for e in entries if e["type"] == "FDE"]
        assert len(fdes) == 1
        # r16 should have register rule pointing to r6
        found = False
        for row in fdes[0]["rows"]:
            if 16 in row["regs"]:
                assert row["regs"][16] == ("register", 6), \
                    f"r16 should be register r6, got {row['regs'][16]}"
                found = True
        assert found, "r16 register rule not found"


class TestDwarf64Format:
    """Verify 64-bit DWARF format (DWARF Section 7.4) parsing."""

    def test_dwarf64_cie_parsed(self, tmp_path):
        """A CIE in 64-bit DWARF format must be recognized as a CIE
        (8-byte CIE_id = 0xFFFFFFFFFFFFFFFF) and decoded correctly."""
        init_instr = cfa_def_cfa(7, 8) + cfa_offset(16, 1)
        cie = build_cie_64(version=4, code_align=1, data_align=1,
                           return_reg=16,
                           initial_instructions=init_instr)
        path = _write_section(tmp_path, "d64cie.bin", cie)
        entries = _run(path)

        cies = [e for e in entries if e["type"] == "CIE"]
        assert len(cies) >= 1, \
            "64-bit DWARF CIE not recognized (CIE_id=0xFFFFFFFFFFFFFFFF)"
        c = cies[0]
        assert c["version"] == 4
        assert c["code_align"] == 1
        assert c["data_align"] == 1
        assert c["return_reg"] == 16

        init_rows = [r for r in c["rows"] if r["loc"] == "initial"]
        assert len(init_rows) == 1
        assert init_rows[0]["cfa_reg"] == 7
        assert init_rows[0]["cfa_off"] == 8

    def test_dwarf64_cie_and_fde(self, tmp_path):
        """64-bit DWARF format CIE + FDE: FDE references CIE correctly
        and inherits initial rules."""
        init_instr = cfa_def_cfa(7, 8) + cfa_offset(16, 1)
        cie = build_cie_64(version=4, code_align=1, data_align=1,
                           return_reg=16,
                           initial_instructions=init_instr)
        fde = build_fde_64(cie_offset=0, initial_location=0x9000,
                           address_range=0x40,
                           instructions=(cfa_advance_loc(4)
                                         + cfa_def_cfa_offset(16)))

        path = _write_section(tmp_path, "d64full.bin", cie + fde)
        entries = _run(path)

        cies = [e for e in entries if e["type"] == "CIE"]
        fdes = [e for e in entries if e["type"] == "FDE"]
        assert len(cies) >= 1, "No CIE found in 64-bit DWARF section"
        assert len(fdes) >= 1, "No FDE found in 64-bit DWARF section"

        # FDE should reference CIE at offset 0
        assert fdes[0]["cie_offset"] == 0
        assert fdes[0]["pc_begin"] == 0x9000
        assert fdes[0]["pc_end"] == 0x9040

        # FDE first row should inherit CIE initial rules
        r0 = fdes[0]["rows"][0]
        assert r0["cfa_reg"] == 7, \
            f"64-bit FDE initial CFA reg: expected 7, got {r0['cfa_reg']}"
        assert r0["cfa_off"] == 8, \
            f"64-bit FDE initial CFA off: expected 8, got {r0['cfa_off']}"

    def test_dwarf64_with_negative_data_align(self, tmp_path):
        """64-bit DWARF with negative data_alignment_factor exercises
        both the 64-bit CIE_id check and SLEB128 decoding."""
        init_instr = cfa_def_cfa(7, 8) + cfa_offset(16, 1)
        cie = build_cie_64(version=4, code_align=1, data_align=-8,
                           return_reg=16,
                           initial_instructions=init_instr)
        path = _write_section(tmp_path, "d64neg.bin", cie)
        entries = _run(path)

        cies = [e for e in entries if e["type"] == "CIE"]
        assert len(cies) >= 1, "64-bit CIE not found"
        assert cies[0]["data_align"] == -8, \
            f"64-bit CIE data_align: expected -8, got {cies[0]['data_align']}"

        init_rows = [r for r in cies[0]["rows"] if r["loc"] == "initial"]
        assert len(init_rows) == 1
        assert init_rows[0]["regs"].get(16) == ("offset", -8), \
            f"64-bit CIE r16: expected [cfa-8], got {init_rows[0]['regs'].get(16)}"


class TestSignedFactored:
    """Verify signed-factored (_sf) CFI opcodes use correct alignment factors."""

    def test_offset_extended_sf_uses_data_align(self, tmp_path):
        """DW_CFA_offset_extended_sf operand must be multiplied by
        data_alignment_factor, not code_alignment_factor.

        code_align=3, data_align=5. offset_extended_sf(r10, 2)
        should give r10=[cfa + 2*5] = [cfa+10], not [cfa + 2*3] = [cfa+6].
        """
        cie = build_cie(version=4, code_align=3, data_align=5,
                        return_reg=16,
                        initial_instructions=b"")
        fde_instr = (cfa_def_cfa(7, 8)
                     + cfa_offset_extended_sf(10, 2)
                     + cfa_advance_loc(1))
        fde = build_fde(cie_offset=0, initial_location=0x8000,
                        address_range=0x20, instructions=fde_instr)

        path = _write_section(tmp_path, "offsetsf.bin", cie + fde)
        entries = _run(path)

        fdes = [e for e in entries if e["type"] == "FDE"]
        assert len(fdes) == 1
        rows = [r for r in fdes[0]["rows"]
                if isinstance(r["loc"], int) and r["loc"] > 0x8000]
        assert len(rows) >= 1, "No rows after advance_loc"
        assert 10 in rows[0]["regs"], "r10 not in output"
        assert rows[0]["regs"][10] == ("offset", 10), \
            f"offset_extended_sf(10,2) with data_align=5: " \
            f"r10 should be [cfa+10], got {rows[0]['regs'][10]}"

    def test_def_cfa_sf_uses_data_align(self, tmp_path):
        """DW_CFA_def_cfa_sf factored offset must be multiplied by
        data_alignment_factor.

        data_align=4. def_cfa_sf(r7, 3) should give cfa=r7+(3*4)=r7+12.
        """
        cie = build_cie(version=4, code_align=1, data_align=4,
                        return_reg=16,
                        initial_instructions=b"")
        fde_instr = (cfa_def_cfa_sf(7, 3)
                     + cfa_advance_loc(1))
        fde = build_fde(cie_offset=0, initial_location=0x7000,
                        address_range=0x20, instructions=fde_instr)

        path = _write_section(tmp_path, "defcfasf.bin", cie + fde)
        entries = _run(path)

        fdes = [e for e in entries if e["type"] == "FDE"]
        assert len(fdes) == 1
        rows = [r for r in fdes[0]["rows"]
                if isinstance(r["loc"], int) and r["loc"] > 0x7000]
        assert len(rows) >= 1, "No rows after advance_loc"
        assert rows[0]["cfa_reg"] == 7, \
            f"def_cfa_sf CFA reg: expected 7, got {rows[0]['cfa_reg']}"
        assert rows[0]["cfa_off"] == 12, \
            f"def_cfa_sf(7,3) with data_align=4: " \
            f"CFA off should be 12, got {rows[0]['cfa_off']}"

    def test_offset_extended_sf_negative(self, tmp_path):
        """DW_CFA_offset_extended_sf with negative factored offset.

        data_align=-8. offset_extended_sf(r6, -2) should give
        r6=[cfa + (-2)*(-8)] = [cfa+16].
        """
        cie = build_cie(version=4, code_align=1, data_align=-8,
                        return_reg=16,
                        initial_instructions=b"")
        fde_instr = (cfa_def_cfa(7, 8)
                     + cfa_offset_extended_sf(6, -2)
                     + cfa_advance_loc(1))
        fde = build_fde(cie_offset=0, initial_location=0x8800,
                        address_range=0x20, instructions=fde_instr)

        path = _write_section(tmp_path, "offsetsfneg.bin", cie + fde)
        entries = _run(path)

        fdes = [e for e in entries if e["type"] == "FDE"]
        assert len(fdes) == 1
        rows = [r for r in fdes[0]["rows"]
                if isinstance(r["loc"], int) and r["loc"] > 0x8800]
        assert len(rows) >= 1
        assert 6 in rows[0]["regs"]
        assert rows[0]["regs"][6] == ("offset", 16), \
            f"offset_extended_sf(6,-2) with data_align=-8: " \
            f"r6 should be [cfa+16], got {rows[0]['regs'][6]}"


class TestValOffset:
    """Verify DW_CFA_val_offset uses data_alignment_factor."""

    def test_val_offset_uses_data_align(self, tmp_path):
        """DW_CFA_val_offset factored_offset must be multiplied by
        data_alignment_factor, not code_alignment_factor.

        code_align=3, data_align=7. val_offset(r10, 2)
        should give r10=val(cfa + 2*7) = val(cfa+14).
        """
        cie = build_cie(version=4, code_align=3, data_align=7,
                        return_reg=16,
                        initial_instructions=b"")
        fde_instr = (cfa_def_cfa(7, 8)
                     + cfa_val_offset(10, 2)
                     + cfa_advance_loc(1))
        fde = build_fde(cie_offset=0, initial_location=0xC000,
                        address_range=0x20, instructions=fde_instr)

        path = _write_section(tmp_path, "valoff.bin", cie + fde)
        entries = _run(path)

        fdes = [e for e in entries if e["type"] == "FDE"]
        assert len(fdes) == 1
        rows = [r for r in fdes[0]["rows"]
                if isinstance(r["loc"], int) and r["loc"] > 0xC000]
        assert len(rows) >= 1
        assert 10 in rows[0]["regs"]
        assert rows[0]["regs"][10] == ("val_offset", 14), \
            f"val_offset(10,2) with data_align=7: " \
            f"r10 should be val(cfa+14), got {rows[0]['regs'][10]}"


class TestDwarf64Combined:
    """Integration tests combining 64-bit DWARF format with signed-factored opcodes."""

    def test_dwarf64_with_signed_factored_opcodes(self, tmp_path):
        """64-bit DWARF format with DW_CFA_def_cfa_sf and DW_CFA_offset_extended_sf.

        This requires the solver to correctly handle:
        - 64-bit CIE_id recognition
        - Signed-factored CFA definition
        - Signed-factored register offset
        - FDE inheriting CIE initial rules
        """
        # CIE: def_cfa_sf(7, 2) with data_align=4 -> cfa=r7+(2*4)=r7+8
        init_instr = cfa_def_cfa_sf(7, 2)
        cie = build_cie_64(version=4, code_align=1, data_align=4,
                           return_reg=16,
                           initial_instructions=init_instr)
        # FDE: offset_extended_sf(10, 3) -> r10=[cfa + 3*4] = [cfa+12]
        fde_instr = (cfa_offset_extended_sf(10, 3)
                     + cfa_advance_loc(1))
        fde = build_fde_64(cie_offset=0, initial_location=0xD000,
                           address_range=0x20,
                           instructions=fde_instr)

        path = _write_section(tmp_path, "d64sf.bin", cie + fde)
        entries = _run(path)

        cies = [e for e in entries if e["type"] == "CIE"]
        assert len(cies) >= 1, "No 64-bit CIE found"

        init_rows = [r for r in cies[0]["rows"] if r["loc"] == "initial"]
        assert len(init_rows) == 1
        assert init_rows[0]["cfa_reg"] == 7
        assert init_rows[0]["cfa_off"] == 8, \
            f"CIE def_cfa_sf(7,2) with da=4: expected cfa=r7+8, " \
            f"got r7{init_rows[0]['cfa_off']:+d}"

        fdes = [e for e in entries if e["type"] == "FDE"]
        assert len(fdes) >= 1, "No 64-bit FDE found"

        # FDE first row inherits CIE initial rules
        r0 = fdes[0]["rows"][0]
        assert r0["cfa_reg"] == 7 and r0["cfa_off"] == 8, \
            f"FDE initial row: expected cfa=r7+8, got r{r0['cfa_reg']}{r0['cfa_off']:+d}"

        # After advance_loc: check r10
        rows = [r for r in fdes[0]["rows"]
                if isinstance(r["loc"], int) and r["loc"] > 0xD000]
        assert len(rows) >= 1
        assert 10 in rows[0]["regs"]
        assert rows[0]["regs"][10] == ("offset", 12), \
            f"offset_extended_sf(10,3) with da=4: " \
            f"r10 should be [cfa+12], got {rows[0]['regs'][10]}"


class TestCrossValidation:
    """Cross-validate decoder against a real compiled binary's .debug_frame."""

    @staticmethod
    def _extract_debug_frame(tmp_path):
        """Compile a test program and attempt to extract .debug_frame."""
        src = tmp_path / "cross.c"
        src.write_text(
            'int factorial(int n) {\n'
            '    if (n <= 1) return 1;\n'
            '    return n * factorial(n - 1);\n'
            '}\n'
            'int main(void) { return factorial(5); }\n'
        )
        elf = str(tmp_path / "cross")
        r = subprocess.run(
            ["gcc", "-gdwarf-4", "-O0",
             "-fno-asynchronous-unwind-tables",
             "-o", elf, str(src)],
            capture_output=True, text=True
        )
        if r.returncode != 0:
            return None, None

        frame_path = str(tmp_path / "frame.bin")
        r = subprocess.run(
            ["objcopy", "--dump-section",
             ".debug_frame=" + frame_path, elf],
            capture_output=True, text=True
        )
        if r.returncode != 0:
            return None, elf
        if not os.path.exists(frame_path) or os.path.getsize(frame_path) == 0:
            return None, elf
        return frame_path, elf

    def test_real_debug_frame(self, tmp_path):
        """Decoder must handle a real .debug_frame section without crashing
        and produce structurally valid output with correct CIE/FDE
        cross-references."""
        frame_path, elf = self._extract_debug_frame(tmp_path)
        if frame_path is None:
            pytest.skip(
                "Could not extract .debug_frame from compiled binary "
                "(compiler may use .eh_frame exclusively)"
            )

        entries = _run(frame_path)

        cies = [e for e in entries if e["type"] == "CIE"]
        fdes = [e for e in entries if e["type"] == "FDE"]
        assert len(cies) >= 1, "No CIEs decoded from real binary"
        assert len(fdes) >= 1, "No FDEs decoded from real binary"

        # Every FDE must reference a known CIE
        cie_offsets = {c["offset"] for c in cies}
        for f in fdes:
            assert f["cie_offset"] in cie_offsets, \
                f"FDE @{hex(f['offset'])} references unknown " \
                f"CIE @{hex(f['cie_offset'])}"

        # Every FDE must have at least one rule row
        for f in fdes:
            assert len(f["rows"]) >= 1, \
                f"FDE @{hex(f['offset'])} has no rule rows"

        # CFA register should be reasonable (< MAX_REGS)
        for f in fdes:
            for row in f["rows"]:
                assert row["cfa_reg"] < 128, \
                    f"Unreasonable CFA register {row['cfa_reg']} in FDE output"
