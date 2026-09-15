
import pytest
import json
import os
import sys
import struct
import importlib.util


@pytest.fixture(scope="session")
def translate_fn():
    """Import translate_scenario function from /app/translate.py"""
    path = "/app/translate.py"
    if not os.path.exists(path):
        pytest.fail("translate.py not found at /app/translate.py")
    spec = importlib.util.spec_from_file_location("translate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "translate_scenario"):
        pytest.fail("translate_scenario function not found in translate.py")
    return mod.translate_scenario


def load_scenario(name):
    with open(f"/app/scenarios/{name}.json") as f:
        return json.load(f)


def _make_pte64(ppn, v=True, r=False, w=False, x=False, u=False,
                g=False, a=False, d=False, rsw=0, pbmt=0, n=0):
    flags = 0
    if v: flags |= 1
    if r: flags |= 2
    if w: flags |= 4
    if x: flags |= 8
    if u: flags |= 16
    if g: flags |= 32
    if a: flags |= 64
    if d: flags |= 128
    flags |= (rsw & 3) << 8
    pte = (ppn << 10) | flags
    pte |= (pbmt & 3) << 61
    pte |= (n & 1) << 63
    return pte


def _pte_hex64(pte_val):
    return "0x" + struct.pack('<Q', pte_val).hex()


def _pte_hex32(pte_val):
    return "0x" + struct.pack('<I', pte_val).hex()


def _make_scenario(xlen, mode, priv, access, va, satp, mstatus, menvcfg, exts, memory):
    return {
        "description": "hidden test",
        "xlen": xlen,
        "translation_mode": mode,
        "privilege": priv,
        "access_type": access,
        "virtual_address": hex(va),
        "satp": hex(satp),
        "mstatus": hex(mstatus),
        "menvcfg": hex(menvcfg),
        "extensions": exts,
        "memory": memory,
    }


ROOT_PPN = 0x80000


def _basic_pt_mem(vpn2, vpn1, vpn0, leaf_ppn, leaf_kwargs):
    """Build a 3-level Sv39 page table with given VPN indices and leaf PTE."""
    mem = {}
    # L2
    mem[hex(ROOT_PPN * 4096 + vpn2 * 8)] = _pte_hex64(_make_pte64(0x80001, v=True))
    # L1
    mem[hex(0x80001 * 4096 + vpn1 * 8)] = _pte_hex64(_make_pte64(0x80002, v=True))
    # L0
    mem[hex(0x80002 * 4096 + vpn0 * 8)] = _pte_hex64(_make_pte64(leaf_ppn, **leaf_kwargs))
    return mem


# VA used in most tests: VPN[2]=2, VPN[1]=1, VPN[0]=2, offset=0x048
VA_STD = 0x0000000080202048
VPN2_STD = 2
VPN1_STD = 1
VPN0_STD = 2


# =============================================================================
# Tests for provided scenarios (in /app/scenarios/)
# =============================================================================

class TestProvidedScenarios:

    def test_sv39_basic_4k(self, translate_fn):
        r = translate_fn(load_scenario("sv39_basic_4k"))
        assert r["outcome"] == "success"
        assert int(r["physical_address"], 16) == 0x80003048
        assert r["page_level"] == 0
        assert r["a_d_update_needed"] is False

    def test_sv39_megapage(self, translate_fn):
        r = translate_fn(load_scenario("sv39_megapage"))
        assert r["outcome"] == "success"
        assert int(r["physical_address"], 16) == 0x80400048
        assert r["page_level"] == 1

    def test_sv39_misaligned_super(self, translate_fn):
        r = translate_fn(load_scenario("sv39_misaligned_super"))
        assert r["outcome"] == "fault"
        assert "page_fault" in r["fault_type"]

    def test_sv39_write_readonly(self, translate_fn):
        r = translate_fn(load_scenario("sv39_write_readonly"))
        assert r["outcome"] == "fault"
        assert r["fault_type"] == "store_page_fault"

    def test_sv39_mxr_exec_read(self, translate_fn):
        r = translate_fn(load_scenario("sv39_mxr_exec_read"))
        assert r["outcome"] == "success"
        assert int(r["physical_address"], 16) == 0x80003048
        pf = r["pte_flags"]
        assert pf["x"] is True
        assert pf["r"] is False

    def test_sv39_no_sum_fault(self, translate_fn):
        r = translate_fn(load_scenario("sv39_no_sum_fault"))
        assert r["outcome"] == "fault"
        assert r["fault_type"] == "load_page_fault"

    def test_sv39_ad_software_fault(self, translate_fn):
        r = translate_fn(load_scenario("sv39_ad_software_fault"))
        assert r["outcome"] == "fault"
        assert r["fault_type"] == "load_page_fault"

    def test_sv39_ad_hardware_update(self, translate_fn):
        r = translate_fn(load_scenario("sv39_ad_hardware_update"))
        assert r["outcome"] == "success"
        assert r["a_d_update_needed"] is True
        assert int(r["physical_address"], 16) == 0x80003048

    def test_sv39_napot_64k(self, translate_fn):
        r = translate_fn(load_scenario("sv39_napot_64k"))
        assert r["outcome"] == "success"
        assert int(r["physical_address"], 16) == 0x80002048
        assert r["page_level"] == 0

    def test_sv39_pbmt_nc(self, translate_fn):
        r = translate_fn(load_scenario("sv39_pbmt_nc"))
        assert r["outcome"] == "success"
        assert r["pbmt_mode"] == "nc"
        assert int(r["physical_address"], 16) == 0x80003048

    def test_sv32_basic(self, translate_fn):
        r = translate_fn(load_scenario("sv32_basic"))
        assert r["outcome"] == "success"
        assert int(r["physical_address"], 16) == 0x80003048
        assert r["page_level"] == 0

    def test_sv48_deep(self, translate_fn):
        r = translate_fn(load_scenario("sv48_deep"))
        assert r["outcome"] == "success"
        assert int(r["physical_address"], 16) == 0x80013048
        assert r["page_level"] == 0


# =============================================================================
# Hidden test scenarios — not present in /app/scenarios/
# These prevent hard-coding results for visible scenarios only.
# =============================================================================

class TestHiddenScenarios:

    def test_sv39_no_mxr_fault(self, translate_fn):
        """Read from X-only page with MXR=0 must fault."""
        mem = _basic_pt_mem(VPN2_STD, VPN1_STD, VPN0_STD, 0x80003,
                            {"v": True, "x": True, "a": True, "d": True})
        s = _make_scenario(64, "Sv39", "S", "read", VA_STD,
                           (8 << 60) | ROOT_PPN, 0, 0, {}, mem)
        r = translate_fn(s)
        assert r["outcome"] == "fault"
        assert r["fault_type"] == "load_page_fault"

    def test_sv39_sum_user_page_success(self, translate_fn):
        """S-mode read from U-page with SUM=1 must succeed."""
        mem = _basic_pt_mem(VPN2_STD, VPN1_STD, VPN0_STD, 0x80003,
                            {"v": True, "r": True, "w": True, "u": True,
                             "a": True, "d": True})
        s = _make_scenario(64, "Sv39", "S", "read", VA_STD,
                           (8 << 60) | ROOT_PPN, 1 << 18, 0, {}, mem)
        r = translate_fn(s)
        assert r["outcome"] == "success"
        assert int(r["physical_address"], 16) == 0x80003048

    def test_sv39_user_kern_fault(self, translate_fn):
        """U-mode accessing S-page (U=0) must fault."""
        mem = _basic_pt_mem(VPN2_STD, VPN1_STD, VPN0_STD, 0x80003,
                            {"v": True, "r": True, "w": True, "u": False,
                             "a": True, "d": True})
        s = _make_scenario(64, "Sv39", "U", "read", VA_STD,
                           (8 << 60) | ROOT_PPN, 0, 0, {}, mem)
        r = translate_fn(s)
        assert r["outcome"] == "fault"
        assert r["fault_type"] == "load_page_fault"

    def test_sv39_dirty_store_fault(self, translate_fn):
        """Store with D=0 and ADUE=0 must fault."""
        mem = _basic_pt_mem(VPN2_STD, VPN1_STD, VPN0_STD, 0x80003,
                            {"v": True, "r": True, "w": True,
                             "a": True, "d": False})
        s = _make_scenario(64, "Sv39", "S", "write", VA_STD,
                           (8 << 60) | ROOT_PPN, 0, 0, {}, mem)
        r = translate_fn(s)
        assert r["outcome"] == "fault"
        assert r["fault_type"] == "store_page_fault"

    def test_sv39_mprv_smode(self, translate_fn):
        """M-mode load with MPRV=1, MPP=S uses S-mode translation."""
        mem = _basic_pt_mem(VPN2_STD, VPN1_STD, VPN0_STD, 0x80003,
                            {"v": True, "r": True, "w": True,
                             "a": True, "d": True})
        mstatus = (1 << 17) | (1 << 11)  # MPRV=1, MPP=01 (S)
        s = _make_scenario(64, "Sv39", "M", "read", VA_STD,
                           (8 << 60) | ROOT_PPN, mstatus, 0, {}, mem)
        r = translate_fn(s)
        assert r["outcome"] == "success"
        assert int(r["physical_address"], 16) == 0x80003048

    def test_sv39_gigapage(self, translate_fn):
        """1GiB L2 superpage, properly aligned."""
        va = 0x00000000C0000048  # VPN[2]=3
        mem = {}
        giga_ppn = 0xC0000  # PPN[1:0] = 0, aligned
        mem[hex(ROOT_PPN * 4096 + 3 * 8)] = _pte_hex64(
            _make_pte64(giga_ppn, v=True, r=True, w=True, x=True,
                        a=True, d=True))
        s = _make_scenario(64, "Sv39", "S", "read", va,
                           (8 << 60) | ROOT_PPN, 0, 0, {}, mem)
        r = translate_fn(s)
        assert r["outcome"] == "success"
        assert int(r["physical_address"], 16) == 0xC0000048
        assert r["page_level"] == 2

    def test_sv39_exec_noexec_fault(self, translate_fn):
        """Execute from R/W page (X=0) must fault."""
        mem = _basic_pt_mem(VPN2_STD, VPN1_STD, VPN0_STD, 0x80003,
                            {"v": True, "r": True, "w": True, "x": False,
                             "a": True, "d": True})
        s = _make_scenario(64, "Sv39", "S", "execute", VA_STD,
                           (8 << 60) | ROOT_PPN, 0, 0, {}, mem)
        r = translate_fn(s)
        assert r["outcome"] == "fault"
        assert r["fault_type"] == "fetch_page_fault"

    def test_sv39_reserved_wr_fault(self, translate_fn):
        """PTE with W=1 R=0 (reserved encoding) must fault."""
        mem = _basic_pt_mem(VPN2_STD, VPN1_STD, VPN0_STD, 0x80003,
                            {"v": True, "r": False, "w": True,
                             "a": True, "d": True})
        s = _make_scenario(64, "Sv39", "S", "read", VA_STD,
                           (8 << 60) | ROOT_PPN, 0, 0, {}, mem)
        r = translate_fn(s)
        assert r["outcome"] == "fault"
        assert "page_fault" in r["fault_type"]

    def test_sv39_invalid_pte(self, translate_fn):
        """PTE with V=0 must fault."""
        mem = _basic_pt_mem(VPN2_STD, VPN1_STD, VPN0_STD, 0x80003,
                            {"v": False, "r": True})
        s = _make_scenario(64, "Sv39", "S", "read", VA_STD,
                           (8 << 60) | ROOT_PPN, 0, 0, {}, mem)
        r = translate_fn(s)
        assert r["outcome"] == "fault"
        assert r["fault_type"] == "load_page_fault"

    def test_sv39_exec_user_page_from_smode(self, translate_fn):
        """S-mode execute from U-page must fault even with SUM=1."""
        mem = _basic_pt_mem(VPN2_STD, VPN1_STD, VPN0_STD, 0x80003,
                            {"v": True, "r": True, "x": True, "u": True,
                             "a": True, "d": True})
        s = _make_scenario(64, "Sv39", "S", "execute", VA_STD,
                           (8 << 60) | ROOT_PPN, 1 << 18, 0, {}, mem)
        r = translate_fn(s)
        assert r["outcome"] == "fault"
        assert r["fault_type"] == "fetch_page_fault"

    def test_sv39_mprv_ifetch_ignores_mprv(self, translate_fn):
        """MPRV does NOT affect instruction fetch — M-mode fetch should not translate."""
        mem = _basic_pt_mem(VPN2_STD, VPN1_STD, VPN0_STD, 0x80003,
                            {"v": True, "r": True, "x": True,
                             "a": True, "d": True})
        mstatus = (1 << 17) | (1 << 11)  # MPRV=1, MPP=S
        s = _make_scenario(64, "Sv39", "M", "execute", VA_STD,
                           (8 << 60) | ROOT_PPN, mstatus, 0, {}, mem)
        r = translate_fn(s)
        # M-mode execute ignores MPRV, so Bare mode, PA = VA
        assert r["outcome"] == "success"
        assert int(r["physical_address"], 16) == VA_STD

    def test_sv39_napot_without_extension(self, translate_fn):
        """NAPOT PTE without Svnapot extension enabled must fault."""
        mem = _basic_pt_mem(VPN2_STD, VPN1_STD, VPN0_STD, 0x80008,
                            {"v": True, "r": True, "w": True,
                             "a": True, "d": True, "n": 1})
        s = _make_scenario(64, "Sv39", "S", "read", VA_STD,
                           (8 << 60) | ROOT_PPN, 0, 0,
                           {"Svnapot": False}, mem)
        r = translate_fn(s)
        # Without Svnapot, N=1 makes PTE invalid
        assert r["outcome"] == "fault"
        assert "page_fault" in r["fault_type"]

    def test_sv39_pbmt_disabled(self, translate_fn):
        """PBMT field in PTE with PBMTE=0 should be ignored (treated as PMA)."""
        mem = _basic_pt_mem(VPN2_STD, VPN1_STD, VPN0_STD, 0x80003,
                            {"v": True, "r": True, "w": True,
                             "a": True, "d": True, "pbmt": 2})
        s = _make_scenario(64, "Sv39", "S", "read", VA_STD,
                           (8 << 60) | ROOT_PPN, 0, 0,
                           {"Svpbmt": True}, mem)
        r = translate_fn(s)
        assert r["outcome"] == "success"
        assert r["pbmt_mode"] == "pma"

    def test_sv39_dirty_hw_update(self, translate_fn):
        """Store with D=0 and ADUE=1 must succeed with a_d_update_needed=True."""
        mem = _basic_pt_mem(VPN2_STD, VPN1_STD, VPN0_STD, 0x80003,
                            {"v": True, "r": True, "w": True,
                             "a": True, "d": False})
        s = _make_scenario(64, "Sv39", "S", "write", VA_STD,
                           (8 << 60) | ROOT_PPN, 0,
                           1 << 61, {}, mem)  # ADUE=1
        r = translate_fn(s)
        assert r["outcome"] == "success"
        assert r["a_d_update_needed"] is True
