"""Tests for differential flash programming optimizer.

Verifies correct differential analysis, erase optimization, multi-format
support, sector cascade behavior, and output format compliance.
"""


import subprocess
import json
import os
import pytest

OPTIMIZER = '/app/optimizer.py'
TARGETS = '/app/targets'
FIRMWARE = '/app/firmware'
CURRENT = '/app/current_state'


def run_optimizer(target, variant, firmware, current_state, output='/tmp/plan.json'):
    """Run the optimizer CLI and return (exit_code, plan_dict_or_None)."""
    result = subprocess.run(
        ['python3', OPTIMIZER,
         '--target', f'{TARGETS}/{target}',
         '--variant', variant,
         '--firmware', f'{FIRMWARE}/{firmware}',
         '--current-state', f'{CURRENT}/{current_state}',
         '--output', output],
        capture_output=True, text=True
    )
    if result.returncode == 0 and os.path.exists(output):
        with open(output) as f:
            return 0, json.load(f)
    return result.returncode, None


class TestCleanFlashOptimization:
    """On clean flash (all erased), erase operations should be skipped
    since programming from erased state never requires bit reversal."""

    def test_clean_flash_skips_erase(self):
        """1024 bytes on clean STM32F4 flash: no erase, just program."""
        code, plan = run_optimizer(
            'stm32f4xx.yaml', 'STM32F407VG', 'small.hex', 'stm32f4_clean.bin')
        assert code == 0
        erase_ops = [op for op in plan['operations'] if op['type'] == 'erase']
        assert len(erase_ops) == 0
        assert plan['statistics']['sectors_erased'] == 0
        assert plan['statistics']['sectors_skipped'] == 1

    def test_clean_flash_programs_correctly(self):
        """Program operation has correct page size and fill bytes."""
        code, plan = run_optimizer(
            'stm32f4xx.yaml', 'STM32F407VG', 'small.hex', 'stm32f4_clean.bin')
        assert code == 0
        prog_ops = [op for op in plan['operations'] if op['type'] == 'program']
        assert len(prog_ops) == 1
        assert prog_ops[0]['size'] == 2048
        assert prog_ops[0]['address'] == 0x08000000
        assert plan['statistics']['fill_bytes'] == 1024
        assert plan['statistics']['bytes_changed'] == 1024

    def test_clean_cross_boundary(self):
        """16KB crossing sector boundary on clean flash: 2 sectors skipped."""
        code, plan = run_optimizer(
            'stm32f4xx.yaml', 'STM32F407VG', 'cross_boundary.hex', 'stm32f4_clean.bin')
        assert code == 0
        assert plan['statistics']['sectors_erased'] == 0
        assert plan['statistics']['sectors_skipped'] == 2
        assert plan['statistics']['pages_programmed'] == 8
        assert plan['statistics']['fill_bytes'] == 0
        assert plan['statistics']['bytes_changed'] == 16384

    def test_clean_nrf_basic(self):
        """6000 bytes on clean nRF52: 2 pages, 2 sectors skipped."""
        code, plan = run_optimizer(
            'nrf52840.yaml', 'nRF52840', 'nrf_basic.hex', 'nrf52_clean.bin')
        assert code == 0
        assert plan['statistics']['sectors_erased'] == 0
        assert plan['statistics']['sectors_skipped'] == 2
        assert plan['statistics']['pages_programmed'] == 2
        assert plan['statistics']['total_program_size'] == 8192
        assert plan['statistics']['fill_bytes'] == 2192
        assert plan['statistics']['bytes_changed'] == 6000


class TestReflashNoOp:
    """Re-flashing identical firmware: current state matches desired,
    so zero operations should be produced."""

    def test_identical_firmware_zero_ops(self):
        code, plan = run_optimizer(
            'stm32f4xx.yaml', 'STM32F407VG', 'small.hex', 'stm32f4_small.bin')
        assert code == 0
        assert len(plan['operations']) == 0
        assert plan['statistics']['sectors_erased'] == 0
        assert plan['statistics']['sectors_skipped'] == 0
        assert plan['statistics']['pages_programmed'] == 0
        assert plan['statistics']['fill_bytes'] == 0
        assert plan['statistics']['bytes_changed'] == 0
        assert plan['statistics']['regions_used'] == []


class TestDifferentialEraseSkip:
    """Erase avoided when current-to-desired transition requires only
    forward bit transitions (erased→programmed direction)."""

    def test_compatible_bit_transition(self):
        """Current=0xF0, Desired=0x00 on 0xFF-erased flash.
        All transitions are 1->0, so erase is unnecessary."""
        code, plan = run_optimizer(
            'nrf52840.yaml', 'nRF52840', 'nrf_incremental.hex', 'nrf52_partial.bin')
        assert code == 0
        erase_ops = [op for op in plan['operations'] if op['type'] == 'erase']
        assert len(erase_ops) == 0
        assert plan['statistics']['sectors_erased'] == 0
        assert plan['statistics']['sectors_skipped'] == 1
        assert plan['statistics']['pages_programmed'] == 1
        assert plan['statistics']['bytes_changed'] == 4096
        assert plan['statistics']['fill_bytes'] == 0


class TestDifferentialEraseRequired:
    """Erase required when bit reversal is needed (programmed→erased)."""

    def test_incompatible_bit_transition(self):
        """Current=0x0F, Desired=0xF0 on 0xFF-erased flash.
        Bits must go 0->1 (programmed->erased), requiring sector erase."""
        code, plan = run_optimizer(
            'nrf52840.yaml', 'nRF52840', 'nrf_erase_needed.hex', 'nrf52_conflict.bin')
        assert code == 0
        erase_ops = [op for op in plan['operations'] if op['type'] == 'erase']
        assert len(erase_ops) == 1
        assert erase_ops[0]['address'] == 0x00000000
        assert erase_ops[0]['size'] == 4096
        assert plan['statistics']['sectors_erased'] == 1
        assert plan['statistics']['sectors_skipped'] == 0
        assert plan['statistics']['pages_programmed'] == 1
        assert plan['statistics']['total_erase_size'] == 4096
        assert plan['statistics']['bytes_changed'] == 4096


class TestMixedEraseDecision:
    """Adjacent sectors with different erase requirements:
    one sector needs erase, the other can skip."""

    def test_mixed_sectors(self):
        """Sector 0: current=0x0F vs desired=0xF0 (erase needed).
        Sector 1: current=0xFF vs desired=0xF0 (skip erase)."""
        code, plan = run_optimizer(
            'nrf52840.yaml', 'nRF52840', 'nrf_mixed.hex', 'nrf52_mixed.bin')
        assert code == 0
        assert plan['statistics']['sectors_erased'] == 1
        assert plan['statistics']['sectors_skipped'] == 1
        assert plan['statistics']['pages_programmed'] == 2
        assert plan['statistics']['total_erase_size'] == 4096
        assert plan['statistics']['bytes_changed'] == 8192

    def test_mixed_operation_ordering(self):
        """Erase operations must precede all program operations."""
        code, plan = run_optimizer(
            'nrf52840.yaml', 'nRF52840', 'nrf_mixed.hex', 'nrf52_mixed.bin')
        assert code == 0
        types = [op['type'] for op in plan['operations']]
        assert types == ['erase', 'program', 'program']


class TestEraseCascadeReprogram:
    """When a sector requires erase, ALL non-erased pages in that sector
    must be reprogrammed, even those identical to the current state,
    because the erase wipes the entire sector."""

    def test_identical_pages_reprogrammed_after_erase(self):
        """16KB sector: pages 0-3 match current state, pages 4-7 conflict.
        Erase wipes everything, so all 8 pages must be reprogrammed."""
        code, plan = run_optimizer(
            'stm32f4xx.yaml', 'STM32F407VG', 'sector_test.hex',
            'stm32f4_sector_test.bin')
        assert code == 0
        assert plan['statistics']['sectors_erased'] == 1
        assert plan['statistics']['sectors_skipped'] == 0
        assert plan['statistics']['pages_programmed'] == 8
        assert plan['statistics']['total_erase_size'] == 16384
        assert plan['statistics']['total_program_size'] == 16384

    def test_cascade_bytes_changed(self):
        """bytes_changed reflects original current vs desired: only
        pages 4-7 actually differ (8192 bytes), not the reprogrammed
        identical pages 0-3."""
        code, plan = run_optimizer(
            'stm32f4xx.yaml', 'STM32F407VG', 'sector_test.hex',
            'stm32f4_sector_test.bin')
        assert code == 0
        assert plan['statistics']['bytes_changed'] == 8192
        assert plan['statistics']['fill_bytes'] == 0


class TestSrecFormat:
    """Motorola S-record format must produce identical results to Intel HEX."""

    def test_srec_matches_hex(self):
        """cross_boundary.srec and cross_boundary.hex yield the same plan."""
        code_h, plan_h = run_optimizer(
            'stm32f4xx.yaml', 'STM32F407VG', 'cross_boundary.hex',
            'stm32f4_clean.bin', '/tmp/plan_hex.json')
        code_s, plan_s = run_optimizer(
            'stm32f4xx.yaml', 'STM32F407VG', 'cross_boundary.srec',
            'stm32f4_clean.bin', '/tmp/plan_srec.json')
        assert code_h == 0
        assert code_s == 0
        assert plan_h['operations'] == plan_s['operations']
        assert plan_h['statistics'] == plan_s['statistics']


class TestMultiRegion:
    """Multi-region target with different erased byte values and
    Motorola S-record firmware input."""

    def test_dual_bank_regions(self):
        """Data in both Bank A (erased=0xFF) and Bank B (erased=0x00)."""
        code, plan = run_optimizer(
            'dual_bank.yaml', 'DB32F100', 'multi_region.srec',
            'dual_bank_clean.bin')
        assert code == 0
        assert sorted(plan['statistics']['regions_used']) == ['Bank A', 'Bank B']
        assert plan['statistics']['sectors_erased'] == 0
        assert plan['statistics']['sectors_skipped'] == 2
        assert plan['statistics']['pages_programmed'] == 2
        assert plan['statistics']['fill_bytes'] == 0
        assert plan['statistics']['bytes_changed'] == 768

    def test_dual_bank_page_sizes(self):
        """Bank A has 512-byte pages, Bank B has 256-byte pages."""
        code, plan = run_optimizer(
            'dual_bank.yaml', 'DB32F100', 'multi_region.srec',
            'dual_bank_clean.bin')
        assert code == 0
        prog_ops = sorted(
            [op for op in plan['operations'] if op['type'] == 'program'],
            key=lambda op: op['address'])
        assert prog_ops[0]['size'] == 512   # Bank A
        assert prog_ops[1]['size'] == 256   # Bank B

    def test_dual_bank_addresses(self):
        """Correct addresses for each bank's program operations."""
        code, plan = run_optimizer(
            'dual_bank.yaml', 'DB32F100', 'multi_region.srec',
            'dual_bank_clean.bin')
        assert code == 0
        prog_ops = sorted(
            [op for op in plan['operations'] if op['type'] == 'program'],
            key=lambda op: op['address'])
        assert prog_ops[0]['address'] == 0x08000000
        assert prog_ops[1]['address'] == 0x10000000


class TestVariableSectorGeometry:
    """STM32F4 variable sectors: 4x16KB + 1x64KB + 7x128KB."""

    def test_non_contiguous_sectors(self):
        """Code in first 16KB sector + data in a 128KB sector."""
        code, plan = run_optimizer(
            'stm32f4xx.yaml', 'STM32F407VG', 'non_contiguous.hex',
            'stm32f4_clean.bin')
        assert code == 0
        assert plan['statistics']['sectors_skipped'] == 2
        assert plan['statistics']['pages_programmed'] == 3
        assert plan['statistics']['bytes_changed'] == 6144
        assert plan['statistics']['fill_bytes'] == 0

    def test_unaligned_within_page(self):
        """500 bytes mid-page: page aligns to region start."""
        code, plan = run_optimizer(
            'stm32f4xx.yaml', 'STM32F407VG', 'unaligned.hex',
            'stm32f4_clean.bin')
        assert code == 0
        prog_ops = [op for op in plan['operations'] if op['type'] == 'program']
        assert len(prog_ops) == 1
        assert prog_ops[0]['address'] == 0x08000000
        assert prog_ops[0]['size'] == 2048
        assert plan['statistics']['fill_bytes'] == 1548
        assert plan['statistics']['bytes_changed'] == 500


class TestAllErasedFirmware:
    """Firmware consisting entirely of the erased byte value."""

    def test_all_ff_no_ops(self):
        """All-0xFF firmware on 0xFF-erased chip: zero operations."""
        code, plan = run_optimizer(
            'stm32f4xx.yaml', 'STM32F407VG', 'all_ff.hex',
            'stm32f4_clean.bin')
        assert code == 0
        assert len(plan['operations']) == 0
        assert plan['statistics']['sectors_erased'] == 0
        assert plan['statistics']['pages_programmed'] == 0
        assert plan['statistics']['fill_bytes'] == 0
        assert plan['statistics']['regions_used'] == []


class TestOverflowDetection:
    """Firmware exceeding flash region boundaries."""

    def test_past_region_end(self):
        """Data extending past flash end exits with code 1."""
        code, plan = run_optimizer(
            'stm32f4xx.yaml', 'STM32F407VG', 'overflow.hex',
            'stm32f4_clean.bin')
        assert code != 0
        assert plan is None


class TestOutputFormat:
    """Output JSON structure, operation ordering, and field presence."""

    def test_required_top_level_fields(self):
        code, plan = run_optimizer(
            'stm32f4xx.yaml', 'STM32F407VG', 'small.hex',
            'stm32f4_clean.bin')
        assert code == 0
        assert plan['target'] == 'STM32F4xx'
        assert plan['variant'] == 'STM32F407VG'
        assert isinstance(plan['operations'], list)
        assert isinstance(plan['statistics'], dict)

    def test_operation_fields(self):
        code, plan = run_optimizer(
            'stm32f4xx.yaml', 'STM32F407VG', 'small.hex',
            'stm32f4_clean.bin')
        assert code == 0
        for op in plan['operations']:
            assert op['type'] in ('erase', 'program')
            assert isinstance(op['region'], str)
            assert isinstance(op['address'], int)
            assert isinstance(op['size'], int)

    def test_statistics_fields(self):
        code, plan = run_optimizer(
            'stm32f4xx.yaml', 'STM32F407VG', 'small.hex',
            'stm32f4_clean.bin')
        assert code == 0
        for field in ['total_erase_size', 'total_program_size', 'sectors_erased',
                       'sectors_skipped', 'pages_programmed', 'fill_bytes',
                       'regions_used', 'bytes_changed']:
            assert field in plan['statistics']

    def test_erases_before_programs(self):
        """All erase operations precede all program operations."""
        code, plan = run_optimizer(
            'nrf52840.yaml', 'nRF52840', 'nrf_mixed.hex',
            'nrf52_mixed.bin')
        assert code == 0
        saw_program = False
        for op in plan['operations']:
            if op['type'] == 'program':
                saw_program = True
            elif op['type'] == 'erase' and saw_program:
                pytest.fail("Erase after program")

    def test_programs_sorted_by_address(self):
        """Program operations sorted by address within each region."""
        code, plan = run_optimizer(
            'stm32f4xx.yaml', 'STM32F407VG', 'non_contiguous.hex',
            'stm32f4_clean.bin')
        assert code == 0
        prog_addrs = [op['address'] for op in plan['operations']
                      if op['type'] == 'program']
        assert prog_addrs == sorted(prog_addrs)

    def test_regions_used_sorted(self):
        """regions_used list is alphabetically sorted."""
        code, plan = run_optimizer(
            'dual_bank.yaml', 'DB32F100', 'multi_region.srec',
            'dual_bank_clean.bin')
        assert code == 0
        assert plan['statistics']['regions_used'] == sorted(
            plan['statistics']['regions_used'])
