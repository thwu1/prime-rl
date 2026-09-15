"""
Pytest tests for ROB binary parser and alignment synthesis engine.

Tests verify correctness of:
  - ROB parser: field extraction, REL/RELA format handling, multi-section
  - Synthesis engine: threshold logic, weak/strong suppression, REL handling
  - Integration: multi-section merger with mixed alignment requirements
"""


import sys
import os
import tempfile

sys.path.insert(0, '/app')

import pytest
from elf_defs import Arch, R_RISCV_ALIGN, R_LARCH_ALIGN
from rob_parser import parse_rob_file
from synth_engine import synthesize_for_section
from merger import merge_sections


# ---------------------------------------------------------------------------
# ROB Binary Parser Tests
# ---------------------------------------------------------------------------

class TestROBParserBasic:
    """ROB binary parser must correctly extract sections and relocations."""

    def test_riscv_bare(self):
        r = parse_rob_file('/app/objects/riscv_bare_a8.rob')
        assert r['arch'] == Arch.RISCV
        assert len(r['sections']) == 1
        s = r['sections'][0]
        assert s.name == '.text'
        assert s.size == 16
        assert s.addralign == 8
        assert len(s.relocations) == 0

    def test_loongarch_bare(self):
        r = parse_rob_file('/app/objects/la_bare_a8.rob')
        assert r['arch'] == Arch.LOONGARCH
        assert len(r['sections']) == 1
        assert r['sections'][0].addralign == 8

    def test_with_rela_reloc(self):
        r = parse_rob_file('/app/objects/riscv_strong_a8.rob')
        s = r['sections'][0]
        assert len(s.relocations) == 1
        rel = s.relocations[0]
        assert rel.r_offset == 0
        assert rel.r_type == R_RISCV_ALIGN
        assert rel.r_addend == 6

    def test_rel_format_no_addend(self):
        r = parse_rob_file('/app/objects/riscv_rel_a8.rob')
        s = r['sections'][0]
        assert len(s.relocations) == 1
        assert s.relocations[0].r_addend is None, \
            "REL-format relocations must have r_addend=None (no explicit addend)"

    def test_loongarch_rel_format(self):
        r = parse_rob_file('/app/objects/la_rel_a8.rob')
        s = r['sections'][0]
        assert len(s.relocations) == 1
        assert s.relocations[0].r_type == R_LARCH_ALIGN
        assert s.relocations[0].r_addend is None, \
            "REL-format relocations must have r_addend=None regardless of arch"

    def test_multi_section(self):
        r = parse_rob_file('/app/objects/riscv_multi.rob')
        assert len(r['sections']) == 2
        assert r['sections'][0].name == '.text.a'
        assert r['sections'][1].name == '.text.b'
        assert len(r['sections'][0].relocations) == 0
        assert len(r['sections'][1].relocations) == 1

    def test_invalid_magic(self):
        with tempfile.NamedTemporaryFile(suffix='.rob', delete=False) as f:
            f.write(b'BADMAGIC01234567')
            tmp = f.name
        try:
            with pytest.raises(ValueError):
                parse_rob_file(tmp)
        finally:
            os.unlink(tmp)

    def test_all_files_parse(self):
        """Every .rob file must parse without error."""
        obj_dir = '/app/objects'
        for fname in sorted(os.listdir(obj_dir)):
            if fname.endswith('.rob'):
                r = parse_rob_file(os.path.join(obj_dir, fname))
                assert 'arch' in r
                assert 'sections' in r
                assert len(r['sections']) >= 1


# ---------------------------------------------------------------------------
# Synthesis Engine Tests
# ---------------------------------------------------------------------------

class TestSynthesisBasic:
    """Sections with no ALIGN relocations should trigger synthesis."""

    def test_riscv_align8(self):
        r = parse_rob_file('/app/objects/riscv_bare_a8.rob')
        _, synth = synthesize_for_section(0, r['sections'][0], r['arch'])
        assert len(synth) == 1
        assert synth[0].addend == 6
        assert synth[0].r_type == R_RISCV_ALIGN

    def test_loongarch_align8(self):
        r = parse_rob_file('/app/objects/la_bare_a8.rob')
        _, synth = synthesize_for_section(0, r['sections'][0], r['arch'])
        assert len(synth) == 1
        assert synth[0].addend == 4
        assert synth[0].r_type == R_LARCH_ALIGN


class TestStrongSuppression:
    """Strong ALIGN at offset 0 must suppress synthesis."""

    def test_riscv_strong(self):
        r = parse_rob_file('/app/objects/riscv_strong_a8.rob')
        _, synth = synthesize_for_section(0, r['sections'][0], r['arch'])
        assert len(synth) == 0

    def test_loongarch_strong(self):
        r = parse_rob_file('/app/objects/la_strong_a16.rob')
        _, synth = synthesize_for_section(0, r['sections'][0], r['arch'])
        assert len(synth) == 0

    def test_overstrong_still_suppresses(self):
        r = parse_rob_file('/app/objects/riscv_overstrong_a8.rob')
        _, synth = synthesize_for_section(0, r['sections'][0], r['arch'])
        assert len(synth) == 0


class TestWeakDoesNotSuppress:
    """Weak ALIGN at offset 0 must NOT suppress synthesis."""

    def test_riscv_weak(self):
        r = parse_rob_file('/app/objects/riscv_weak_a8.rob')
        _, synth = synthesize_for_section(0, r['sections'][0], r['arch'])
        assert len(synth) == 1, "Weak ALIGN (addend=2 < needed=6) must not suppress"
        assert synth[0].addend == 6

    def test_loongarch_weak(self):
        r = parse_rob_file('/app/objects/la_weak_a16.rob')
        _, synth = synthesize_for_section(0, r['sections'][0], r['arch'])
        assert len(synth) == 1, "Weak ALIGN (addend=4 < needed=12) must not suppress"
        assert synth[0].addend == 12

    def test_borderline_weak(self):
        r = parse_rob_file('/app/objects/riscv_borderline.rob')
        _, synth = synthesize_for_section(0, r['sections'][0], r['arch'])
        assert len(synth) == 1, "Borderline weak (addend=4 < needed=6) must synthesize"


class TestRELFormat:
    """REL-format ALIGNs (no explicit addend) must not suppress synthesis."""

    def test_riscv_rel(self):
        r = parse_rob_file('/app/objects/riscv_rel_a8.rob')
        _, synth = synthesize_for_section(0, r['sections'][0], r['arch'])
        assert len(synth) == 1, "REL format (no addend) must not suppress synthesis"
        assert synth[0].addend == 6

    def test_loongarch_rel(self):
        r = parse_rob_file('/app/objects/la_rel_a8.rob')
        _, synth = synthesize_for_section(0, r['sections'][0], r['arch'])
        assert len(synth) == 1, "REL format (no addend) must not suppress synthesis"
        assert synth[0].addend == 4


class TestThresholds:
    """Architecture-specific alignment thresholds."""

    def test_riscv_at_threshold(self):
        r = parse_rob_file('/app/objects/riscv_threshold_a4.rob')
        _, synth = synthesize_for_section(0, r['sections'][0], r['arch'])
        assert len(synth) == 1
        assert synth[0].addend == 2

    def test_riscv_below_threshold(self):
        r = parse_rob_file('/app/objects/riscv_below_a2.rob')
        _, synth = synthesize_for_section(0, r['sections'][0], r['arch'])
        assert len(synth) == 0

    def test_loongarch_at_boundary(self):
        r = parse_rob_file('/app/objects/la_boundary_a4.rob')
        _, synth = synthesize_for_section(0, r['sections'][0], r['arch'])
        assert len(synth) == 0, \
            "LoongArch align=4 should NOT synthesize (threshold is >4, not >=4)"


class TestInteriorOffset:
    """Interior ALIGNs must not affect boundary synthesis decision."""

    def test_interior_does_not_suppress(self):
        r = parse_rob_file('/app/objects/riscv_interior_a8.rob')
        _, synth = synthesize_for_section(0, r['sections'][0], r['arch'])
        assert len(synth) == 1
        assert synth[0].addend == 6


class TestDotAdvancement:
    """Dot position must advance correctly through synthesis and content."""

    def test_with_synthesis(self):
        r = parse_rob_file('/app/objects/riscv_bare_a8.rob')
        new_dot, synth = synthesize_for_section(100, r['sections'][0], r['arch'])
        assert len(synth) == 1
        assert new_dot == 122  # 100 + 6 (addend) + 16 (size)

    def test_without_synthesis(self):
        r = parse_rob_file('/app/objects/riscv_strong_a8.rob')
        new_dot, synth = synthesize_for_section(100, r['sections'][0], r['arch'])
        assert len(synth) == 0
        assert new_dot == 116  # 100 + 16 (size)


class TestMultiSectionMerge:
    """Integration test for multi-section merging via merger.py."""

    def test_merge_with_weak(self):
        r = parse_rob_file('/app/objects/riscv_multi.rob')
        merge = merge_sections(r['sections'], r['arch'])
        synth = merge['synthesized']
        assert len(synth) == 2, "Both sections need synthesis"
        addends = sorted([s.addend for s in synth])
        assert addends == [2, 6]
