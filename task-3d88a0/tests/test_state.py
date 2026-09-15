
import json
import struct
import os
import pytest

PHYS_SIZE = 4 * 1024 * 1024


def normalize_hex(s):
    """Convert hex string or int to int for comparison."""
    if isinstance(s, int):
        return s
    s = str(s).strip().lower()
    if s.startswith('0x'):
        return int(s, 16)
    try:
        return int(s, 16)
    except ValueError:
        return int(s)


def read_u64(data, offset):
    return struct.unpack('<Q', data[offset:offset + 8])[0]


@pytest.fixture(scope="session")
def report():
    with open('/app/report.json') as f:
        return json.load(f)


@pytest.fixture(scope="session")
def fixed_mem():
    with open('/app/memory_fixed.bin', 'rb') as f:
        return f.read()


# ---------------------------------------------------------------------------
# Report structure
# ---------------------------------------------------------------------------
class TestReportStructure:
    def test_report_exists(self):
        assert os.path.exists('/app/report.json'), "report.json not found"

    def test_fixed_memory_exists(self):
        assert os.path.exists('/app/memory_fixed.bin'), "memory_fixed.bin not found"

    def test_required_fields(self, report):
        for field in ['cr3', 'physical_memory_size', 'total_mapped_entries',
                      'memory_map', 'anomalies', 'crash_root_cause']:
            assert field in report, f"Missing required field: {field}"


# ---------------------------------------------------------------------------
# Basic analysis correctness
# ---------------------------------------------------------------------------
class TestBasicAnalysis:
    def test_cr3_value(self, report):
        assert normalize_hex(report['cr3']) == 0x1000

    def test_physical_memory_size(self, report):
        assert report['physical_memory_size'] == PHYS_SIZE

    def test_total_mapped_entries(self, report):
        assert report['total_mapped_entries'] == 19

    def test_memory_map_count(self, report):
        assert len(report['memory_map']) == 19


# ---------------------------------------------------------------------------
# Memory map verification
# ---------------------------------------------------------------------------
class TestMemoryMap:
    def _vaddr_set(self, report):
        return {normalize_hex(e['virtual_address']) for e in report['memory_map']}

    def test_identity_mapped_pages(self, report):
        """First few 4KB identity-mapped user pages should be present."""
        vaddrs = self._vaddr_set(report)
        for addr in [0x0, 0x1000, 0x2000, 0x3000, 0x5000]:
            assert addr in vaddrs, f"Missing mapping at {addr:#x}"

    def test_valid_huge_page(self, report):
        """Correctly configured 2MB huge page at virtual 0x200000."""
        found = False
        for e in report['memory_map']:
            if normalize_hex(e['virtual_address']) == 0x200000:
                assert e['size'] == 2097152
                assert normalize_hex(e['physical_address']) == 0x200000
                found = True
                break
        assert found, "Missing valid 2MB huge page at 0x200000"

    def test_misaligned_huge_page_listed(self, report):
        """Anomalous 2MB huge page at 0x400000 should still appear in memory_map."""
        found = False
        for e in report['memory_map']:
            if normalize_hex(e['virtual_address']) == 0x400000:
                assert e['size'] == 2097152
                found = True
                break
        assert found, "Misaligned huge page at 0x400000 should be in memory_map"

    def test_kernel_pages_mapped(self, report):
        """All four kernel pages should appear."""
        vaddrs = self._vaddr_set(report)
        for addr in [0xFFFF800000000000, 0xFFFF800000001000,
                     0xFFFF800000002000, 0xFFFF800000003000]:
            assert addr in vaddrs, f"Missing kernel mapping at {addr:#018x}"

    def test_unreachable_pages_excluded(self, report):
        """PD[4] has PRESENT cleared: pages at 0x800000+ must NOT be in map."""
        vaddrs = self._vaddr_set(report)
        assert 0x800000 not in vaddrs, "0x800000 should be unreachable"
        assert 0x801000 not in vaddrs, "0x801000 should be unreachable"

    def test_pd3_data_region(self, report):
        """Pages under PD[3] should be mapped."""
        vaddrs = self._vaddr_set(report)
        assert 0x600000 in vaddrs, "Missing mapping at 0x600000"
        assert 0x601000 in vaddrs, "Missing mapping at 0x601000"


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------
class TestAnomalies:
    def _find_by_location(self, report, phys_loc):
        for a in report['anomalies']:
            if normalize_hex(a['entry_physical_location']) == phys_loc:
                return a
        return None

    def test_anomaly_count(self, report):
        assert len(report['anomalies']) >= 6, \
            f"Expected at least 6 anomalies, found {len(report['anomalies'])}"

    def test_self_referencing_pte(self, report):
        """PT[4] at phys 0x4020 maps virt 0x4000 to its own page table frame."""
        a = self._find_by_location(report, 0x4020)
        assert a is not None, "Self-referencing PTE not found (entry at 0x4020)"
        assert normalize_hex(a['entry_current_value']) == 0x4007

    def test_oob_physical_address(self, report):
        """PT[10] at phys 0x4050 points beyond 4MB physical memory."""
        a = self._find_by_location(report, 0x4050)
        assert a is not None, "OOB physical address not found (entry at 0x4050)"
        assert normalize_hex(a['entry_current_value']) == 0x500007

    def test_misaligned_huge_page(self, report):
        """PD[2] at phys 0x3010: 2MB huge page with non-2MB-aligned phys addr."""
        a = self._find_by_location(report, 0x3010)
        assert a is not None, "Misaligned huge page not found (entry at 0x3010)"
        assert normalize_hex(a['entry_current_value']) == 0x201087
        corrected = normalize_hex(a['entry_corrected_value'])
        phys = corrected & 0x000FFFFFFFFFF000
        assert phys % (2 * 1024 * 1024) == 0, \
            f"Corrected phys addr {phys:#x} not 2MB-aligned"
        assert corrected & 0x81, "Corrected entry must retain PRESENT and HUGE_PAGE"

    def test_not_present_intermediate(self, report):
        """PD[4] at phys 0x3020: PRESENT cleared despite valid child PT."""
        a = self._find_by_location(report, 0x3020)
        assert a is not None, "Not-present intermediate not found (entry at 0x3020)"
        assert normalize_hex(a['entry_current_value']) == 0x9006
        corrected = normalize_hex(a['entry_corrected_value'])
        assert corrected & 1, "Corrected PD entry must have PRESENT"
        assert (corrected & 0x000FFFFFFFFFF000) == 0x9000, \
            "Corrected PD entry should still point to PT at 0x9000"

    def test_nx_on_pml4_entry(self, report):
        """PML4[256] at phys 0x1800: NX bit blocks kernel code execution."""
        a = self._find_by_location(report, 0x1800)
        assert a is not None, "NX on PML4 entry not found (entry at 0x1800)"
        assert normalize_hex(a['entry_current_value']) == 0x8000000000006003
        corrected = normalize_hex(a['entry_corrected_value'])
        assert not (corrected & (1 << 63)), "Corrected PML4 entry must not have NX"
        assert corrected & 1, "Corrected PML4 entry must be PRESENT"

    def test_writable_masked_at_pd(self, report):
        """Kernel PD[0] at phys 0x7000: WRITABLE missing, leaf PTEs have it."""
        a = self._find_by_location(report, 0x7000)
        assert a is not None, "Writable masked not found (entry at 0x7000)"
        assert normalize_hex(a['entry_current_value']) == 0x8001
        corrected = normalize_hex(a['entry_corrected_value'])
        assert corrected & 2, "Corrected PD entry must have WRITABLE"
        assert corrected & 1, "Corrected PD entry must be PRESENT"


# ---------------------------------------------------------------------------
# Crash root cause
# ---------------------------------------------------------------------------
class TestCrashAnalysis:
    def test_mentions_write_permission(self, report):
        cause = report['crash_root_cause'].lower()
        assert any(w in cause for w in ['write', 'writable', 'read-only', 'readonly']), \
            "Root cause should mention write permission issue"

    def test_mentions_faulting_address(self, report):
        cause = report['crash_root_cause'].lower().replace(' ', '')
        assert 'ffff800000002000' in cause, \
            "Root cause should reference faulting address 0xffff800000002000"


# ---------------------------------------------------------------------------
# Fixed memory binary
# ---------------------------------------------------------------------------
class TestFixedMemory:
    def test_size_matches(self, fixed_mem):
        assert len(fixed_mem) == PHYS_SIZE

    def test_pml4_256_nx_cleared(self, fixed_mem):
        entry = read_u64(fixed_mem, 0x1800)
        assert not (entry & (1 << 63)), "PML4[256] NX should be cleared"
        assert entry & 1, "PML4[256] must remain PRESENT"
        assert entry & 2, "PML4[256] must remain WRITABLE"

    def test_pd4_present_set(self, fixed_mem):
        entry = read_u64(fixed_mem, 0x3020)
        assert entry & 1, "PD[4] PRESENT bit should now be set"
        pt_addr = entry & 0x000FFFFFFFFFF000
        assert pt_addr == 0x9000, "PD[4] should still point to PT at 0x9000"

    def test_kernel_pd_writable(self, fixed_mem):
        entry = read_u64(fixed_mem, 0x7000)
        assert entry & 2, "Kernel PD[0] WRITABLE bit should now be set"
        assert entry & 1, "Kernel PD[0] must remain PRESENT"

    def test_huge_page_aligned(self, fixed_mem):
        entry = read_u64(fixed_mem, 0x3010)
        phys = entry & 0x000FFFFFFFFFF000
        assert phys % (2 * 1024 * 1024) == 0, \
            f"Huge page phys addr {phys:#x} must be 2MB-aligned"

    def test_self_ref_resolved(self, fixed_mem):
        entry = read_u64(fixed_mem, 0x4020)
        if entry & 1:
            phys = entry & 0x000FFFFFFFFFF000
            assert phys != 0x4000, "PT[4] must no longer self-reference"

    def test_oob_resolved(self, fixed_mem):
        entry = read_u64(fixed_mem, 0x4050)
        if entry & 1:
            phys = entry & 0x000FFFFFFFFFF000
            assert phys < PHYS_SIZE, \
                f"PT[10] phys addr {phys:#x} must be within 4MB"

    def test_valid_entries_unmodified(self, fixed_mem):
        """Valid page table entries should not be altered by fixes."""
        assert read_u64(fixed_mem, 0x1000) == 0x2007, "PML4[0] should be unchanged"
        assert read_u64(fixed_mem, 0x2000) == 0x3007, "PDPT[0] should be unchanged"
        assert read_u64(fixed_mem, 0x3000) == 0x4007, "PD[0] should be unchanged"
        assert read_u64(fixed_mem, 0x3008) == 0x200087, "PD[1] huge page unchanged"
