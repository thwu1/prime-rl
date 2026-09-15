"""
Tests for x86-64 page table forensics & security hardening task.

Verifies: CR3 discovery, corruption identification, binary repair,
W^X audit, hardened page tables, and security posture evaluation.

"""
import json
import struct
import pytest


def hex_to_int(s):
    if isinstance(s, int):
        return s
    return int(str(s).strip(), 16)


def load_json(path):
    with open(path) as f:
        return json.load(f)


# ============================================================
# Page table helpers for verification
# ============================================================

def read_entry(mem, offset):
    if offset + 8 > len(mem):
        return None
    return struct.unpack_from('<Q', mem, offset)[0]


def entry_present(e):
    return bool(e & 1)

def entry_rw(e):
    return bool(e & 2)

def entry_us(e):
    return bool(e & 4)

def entry_ps(e):
    return bool(e & 0x80)

def entry_nx(e):
    return bool(e & (1 << 63))

def phys_4k(e):
    return e & 0x000FFFFFFFFFF000

def phys_2m(e):
    return e & 0x000FFFFFFFE00000

def sign_extend(addr):
    if addr & (1 << 47):
        return addr | 0xFFFF000000000000
    return addr


def walk_all(mem, cr3):
    """Full 4-level page table walk. Returns list of (va, pa, size, w, x, u)."""
    results = []
    for i4 in range(512):
        e4 = read_entry(mem, cr3 + i4 * 8)
        if e4 is None or not entry_present(e4):
            continue
        rw4, us4, nx4 = entry_rw(e4), entry_us(e4), entry_nx(e4)
        for i3 in range(512):
            e3 = read_entry(mem, phys_4k(e4) + i3 * 8)
            if e3 is None or not entry_present(e3):
                continue
            rw3, us3, nx3 = entry_rw(e3), entry_us(e3), entry_nx(e3)
            if entry_ps(e3):
                raw = (i4 << 39) | (i3 << 30)
                va = sign_extend(raw)
                results.append((va, e3 & 0x000FFFFFC0000000, 1 << 30,
                                rw4 and rw3, not (nx4 or nx3), us4 and us3))
                continue
            for i2 in range(512):
                e2 = read_entry(mem, phys_4k(e3) + i2 * 8)
                if e2 is None or not entry_present(e2):
                    continue
                rw2, us2, nx2 = entry_rw(e2), entry_us(e2), entry_nx(e2)
                if entry_ps(e2):
                    raw = (i4 << 39) | (i3 << 30) | (i2 << 21)
                    va = sign_extend(raw)
                    results.append((va, phys_2m(e2), 1 << 21,
                                    rw4 and rw3 and rw2,
                                    not (nx4 or nx3 or nx2),
                                    us4 and us3 and us2))
                    continue
                for i1 in range(512):
                    e1 = read_entry(mem, phys_4k(e2) + i1 * 8)
                    if e1 is None or not entry_present(e1):
                        continue
                    rw1, us1, nx1 = entry_rw(e1), entry_us(e1), entry_nx(e1)
                    raw = (i4 << 39) | (i3 << 30) | (i2 << 21) | (i1 << 12)
                    va = sign_extend(raw)
                    results.append((va, phys_4k(e1), 4096,
                                    rw4 and rw3 and rw2 and rw1,
                                    not (nx4 or nx3 or nx2 or nx1),
                                    us4 and us3 and us2 and us1))
    return results


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="module")
def cr3_data():
    return load_json("/app/output/cr3.json")

@pytest.fixture(scope="module")
def corruptions():
    return load_json("/app/output/corruptions.json")

@pytest.fixture(scope="module")
def repaired():
    with open("/app/output/repaired.bin", "rb") as f:
        return f.read()

@pytest.fixture(scope="module")
def audit():
    return load_json("/app/output/audit.json")

@pytest.fixture(scope="module")
def hardened():
    with open("/app/output/hardened.bin", "rb") as f:
        return f.read()

@pytest.fixture(scope="module")
def posture():
    return load_json("/app/output/posture.json")


# ============================================================
# CR3 Discovery
# ============================================================

class TestCR3Discovery:

    def test_cr3_key_present(self, cr3_data):
        assert "cr3" in cr3_data

    def test_cr3_value(self, cr3_data):
        assert cr3_data["cr3"] == 0x5000

    def test_cr3_not_decoy_1(self, cr3_data):
        assert cr3_data["cr3"] != 0x0000

    def test_cr3_not_decoy_2(self, cr3_data):
        assert cr3_data["cr3"] != 0x4000


# ============================================================
# Corruption Identification
# ============================================================

class TestCorruptions:

    def _find(self, corruptions, offset):
        for c in corruptions:
            if c["byte_offset"] == offset:
                return c
        return None

    def test_count(self, corruptions):
        assert len(corruptions) == 4

    def test_sorted(self, corruptions):
        offsets = [c["byte_offset"] for c in corruptions]
        assert offsets == sorted(offsets)

    def test_address_bitflip(self, corruptions):
        c = self._find(corruptions, 0xB028)
        assert c is not None
        assert c["corruption_type"] == "address_bitflip"
        assert hex_to_int(c["corrupted_value"]) == 0x0000000000300005
        assert hex_to_int(c["corrected_value"]) == 0x0000000000200005
        assert hex_to_int(c["virtual_address"]) == 0x0000008000005000

    def test_unauthorized_mapping(self, corruptions):
        c = self._find(corruptions, 0xB038)
        assert c is not None
        assert c["corruption_type"] == "unauthorized_mapping"
        assert hex_to_int(c["corrupted_value"]) == 0x0000000000303007
        assert hex_to_int(c["corrected_value"]) == 0
        assert hex_to_int(c["virtual_address"]) == 0x0000008000007000

    def test_nx_injected(self, corruptions):
        c = self._find(corruptions, 0xE000)
        assert c is not None
        assert c["corruption_type"] == "nx_injected"
        assert hex_to_int(c["corrupted_value"]) == 0x8000000000300001
        assert hex_to_int(c["corrected_value"]) == 0x0000000000300001
        assert hex_to_int(c["virtual_address"]) == 0xFFFFFF8000000000

    def test_present_cleared(self, corruptions):
        c = self._find(corruptions, 0xE008)
        assert c is not None
        assert c["corruption_type"] == "present_cleared"
        assert hex_to_int(c["corrupted_value"]) == 0x8000000000301002
        assert hex_to_int(c["corrected_value"]) == 0x8000000000301003
        assert hex_to_int(c["virtual_address"]) == 0xFFFFFF8000001000


# ============================================================
# Repaired Binary
# ============================================================

class TestRepairedBinary:

    def test_file_size(self, repaired):
        assert len(repaired) == 81920

    def test_fixed_nx(self, repaired):
        assert struct.unpack_from('<Q', repaired, 0xE000)[0] == 0x0000000000300001

    def test_fixed_present(self, repaired):
        assert struct.unpack_from('<Q', repaired, 0xE008)[0] == 0x8000000000301003

    def test_fixed_bitflip(self, repaired):
        assert struct.unpack_from('<Q', repaired, 0xB028)[0] == 0x0000000000200005

    def test_fixed_unauthorized(self, repaired):
        assert struct.unpack_from('<Q', repaired, 0xB038)[0] == 0x0000000000000000

    def test_pml4_preserved(self, repaired):
        assert struct.unpack_from('<Q', repaired, 0x5000)[0] == 0x0000000000006003

    def test_pt_low_preserved(self, repaired):
        assert struct.unpack_from('<Q', repaired, 0x8000)[0] == 0x0000000000100001

    def test_decoy1_preserved(self, repaired):
        assert struct.unpack_from('<Q', repaired, 0x0000)[0] == 0x0000000000001003

    def test_decoy2_preserved(self, repaired):
        assert struct.unpack_from('<Q', repaired, 0x4000)[0] == 0x0000000000020003

    def test_kern_rodata_preserved(self, repaired):
        assert struct.unpack_from('<Q', repaired, 0xE010)[0] == 0x8000000000302005

    def test_kern_rwx_preserved(self, repaired):
        """The intentional W^X page is NOT a corruption — it stays in repaired."""
        assert struct.unpack_from('<Q', repaired, 0xE018)[0] == 0x0000000000303003


# ============================================================
# W^X Audit (repaired state)
# ============================================================

class TestSecurityAudit:

    def _find_va(self, audit, va):
        for a in audit:
            if hex_to_int(a["virtual_address"]) == va:
                return a
        return None

    def test_count(self, audit):
        assert len(audit) == 3

    def test_sorted(self, audit):
        vas = [hex_to_int(a["virtual_address"]) for a in audit]
        assert vas == sorted(vas)

    def test_wx_low(self, audit):
        a = self._find_va(audit, 0x3000)
        assert a is not None
        assert hex_to_int(a["physical_address"]) == 0x103000
        assert a["page_size"] == 4096
        assert a["writable"] is True
        assert a["executable"] is True
        assert a["user_accessible"] is False

    def test_wx_user_2mb(self, audit):
        a = self._find_va(audit, 0x0000323200000000)
        assert a is not None
        assert hex_to_int(a["physical_address"]) == 0x1000000
        assert a["page_size"] == 2097152
        assert a["writable"] is True
        assert a["executable"] is True
        assert a["user_accessible"] is True

    def test_wx_kernel(self, audit):
        a = self._find_va(audit, 0xFFFFFF8000003000)
        assert a is not None
        assert hex_to_int(a["physical_address"]) == 0x303000
        assert a["page_size"] == 4096
        assert a["writable"] is True
        assert a["executable"] is True
        assert a["user_accessible"] is False

    def test_no_false_positive(self, audit):
        for a in audit:
            assert hex_to_int(a["virtual_address"]) != 0x0000008000007000


# ============================================================
# Hardened Binary (W^X remediation)
# ============================================================

class TestHardenedBinary:

    def test_file_size(self, hardened):
        assert len(hardened) == 81920

    def test_low_rwx_nx_set(self, hardened):
        """PT_low[3] at 0x8018: NX bit set to fix W^X at VA 0x3000."""
        val = struct.unpack_from('<Q', hardened, 0x8018)[0]
        assert val == 0x8000000000103003

    def test_kern_rwx_nx_set(self, hardened):
        """PT_kern[3] at 0xE018: NX bit set to fix W^X at VA 0xFFFFFF8000003000."""
        val = struct.unpack_from('<Q', hardened, 0xE018)[0]
        assert val == 0x8000000000303003

    def test_2mb_page_demoted_pd(self, hardened):
        """PD_mid[0] at 0x10000: now points to new PT (no PS bit)."""
        val = struct.unpack_from('<Q', hardened, 0x10000)[0]
        assert val == 0x0000000000011007  # PA 0x11000, P, RW, US, no PS

    def test_new_pt_first_entry(self, hardened):
        """New PT at 0x11000 entry 0: PA 0x1000000, P, RW, US, NX."""
        val = struct.unpack_from('<Q', hardened, 0x11000)[0]
        assert val == 0x8000000001000007

    def test_new_pt_mid_entry(self, hardened):
        """New PT at 0x11000 entry 255: PA 0x10FF000."""
        val = struct.unpack_from('<Q', hardened, 0x11000 + 255 * 8)[0]
        assert val == 0x80000000010FF007

    def test_new_pt_last_entry(self, hardened):
        """New PT at 0x11000 entry 511: PA 0x11FF000."""
        val = struct.unpack_from('<Q', hardened, 0x11000 + 511 * 8)[0]
        assert val == 0x80000000011FF007

    def test_no_wx_violations(self, hardened):
        """Full walk on hardened dump must yield zero W^X violations."""
        regions = walk_all(hardened, 0x5000)
        wx = [(va, pa) for va, pa, sz, w, x, u in regions if w and x]
        assert wx == [], f"Unexpected W^X violations: {wx}"

    def test_repaired_entries_preserved(self, hardened):
        """Repaired corruption fixes must be preserved in hardened."""
        assert struct.unpack_from('<Q', hardened, 0xE000)[0] == 0x0000000000300001  # .text fix
        assert struct.unpack_from('<Q', hardened, 0xE008)[0] == 0x8000000000301003  # .data fix
        assert struct.unpack_from('<Q', hardened, 0xB028)[0] == 0x0000000000200005  # bitflip fix
        assert struct.unpack_from('<Q', hardened, 0xB038)[0] == 0x0000000000000000  # unauth fix

    def test_decoys_preserved(self, hardened):
        """Decoy structures must be untouched."""
        assert struct.unpack_from('<Q', hardened, 0x0000)[0] == 0x0000000000001003
        assert struct.unpack_from('<Q', hardened, 0x4000)[0] == 0x0000000000020003

    def test_2mb_demotion_total_pages(self, hardened):
        """Demoted 2MB region should produce 512 present 4KB pages."""
        regions = walk_all(hardened, 0x5000)
        base_va = 0x0000323200000000
        pages = [r for r in regions if r[0] >= base_va and r[0] < base_va + (1 << 21)]
        assert len(pages) == 512


# ============================================================
# Security Posture Evaluation
# ============================================================

class TestPosture:

    def test_corrupted_wx(self, posture):
        assert posture["corrupted"]["wx_violations"] == 4

    def test_corrupted_privesc(self, posture):
        assert posture["corrupted"]["privilege_escalation_paths"] == 1

    def test_corrupted_unmapped(self, posture):
        assert posture["corrupted"]["unmapped_critical_pages"] == 1

    def test_repaired_wx(self, posture):
        assert posture["repaired"]["wx_violations"] == 3

    def test_repaired_privesc(self, posture):
        assert posture["repaired"]["privilege_escalation_paths"] == 0

    def test_repaired_unmapped(self, posture):
        assert posture["repaired"]["unmapped_critical_pages"] == 0

    def test_hardened_wx(self, posture):
        assert posture["hardened"]["wx_violations"] == 0

    def test_hardened_privesc(self, posture):
        assert posture["hardened"]["privilege_escalation_paths"] == 0

    def test_hardened_unmapped(self, posture):
        assert posture["hardened"]["unmapped_critical_pages"] == 0

    def test_remediation_count(self, posture):
        assert len(posture["remediation"]) == 3

    def test_remediation_sorted(self, posture):
        vas = [hex_to_int(r["virtual_address"]) for r in posture["remediation"]]
        assert vas == sorted(vas)

    def test_remediation_low_nx(self, posture):
        r = posture["remediation"][0]
        assert hex_to_int(r["virtual_address"]) == 0x0000000000003000
        assert r["original_permissions"] == "RWX"
        assert r["hardened_permissions"] == "RW-"
        assert r["method"] == "nx_set"

    def test_remediation_2mb_demotion(self, posture):
        r = posture["remediation"][1]
        assert hex_to_int(r["virtual_address"]) == 0x0000323200000000
        assert r["original_permissions"] == "RWX"
        assert r["hardened_permissions"] == "RW-"
        assert r["method"] == "large_page_demotion"

    def test_remediation_kern_nx(self, posture):
        r = posture["remediation"][2]
        assert hex_to_int(r["virtual_address"]) == 0xFFFFFF8000003000
        assert r["original_permissions"] == "RWX"
        assert r["hardened_permissions"] == "RW-"
        assert r["method"] == "nx_set"
