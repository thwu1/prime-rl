
import json
import os
import xml.etree.ElementTree as ET

import pytest


# ── Helpers ──────────────────────────────────────────────────────────


def _parse_svd(path="/app/fixed_device.svd"):
    assert os.path.exists(path), f"Fixed SVD not found at {path}"
    return ET.parse(path)


def _find_peripheral(root, name):
    for p in root.find("peripherals"):
        if p.find("name").text == name:
            return p
    return None


def _find_register(periph, name):
    regs = periph.find("registers")
    if regs is None:
        return None
    for r in regs:
        n = r.find("name")
        if n is not None and n.text == name:
            return r
    return None


def _find_field(reg, name):
    fields = reg.find("fields")
    if fields is None:
        return None
    for f in fields:
        n = f.find("name")
        if n is not None and n.text == name:
            return f
    return None


def _hex_val(v):
    """Accept int, hex-string, or plain int for bitmap/mask fields."""
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        return int(v, 0)
    return int(v)


@pytest.fixture(scope="session")
def svd():
    return _parse_svd()


@pytest.fixture(scope="session")
def svd_root(svd):
    return svd.getroot()


@pytest.fixture(scope="session")
def audit():
    path = "/app/codegen_audit.json"
    assert os.path.exists(path), f"Codegen audit not found at {path}"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def corrected():
    path = "/app/codegen_corrected.json"
    assert os.path.exists(path), f"Corrected codegen not found at {path}"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def hazard():
    path = "/app/hazard_assessment.json"
    assert os.path.exists(path), f"Hazard assessment not found at {path}"
    with open(path) as f:
        return json.load(f)


# ── Fixed SVD Structure Tests ────────────────────────────────────────


class TestFixedSVDStructure:
    """Verify the corrected SVD has valid structure."""

    def test_svd_is_valid_xml(self, svd):
        assert svd is not None

    def test_has_all_peripherals(self, svd_root):
        names = {p.find("name").text for p in svd_root.find("peripherals")}
        assert names >= {"TIMER0", "DMA", "GPIOA", "GPIOB"}


# ── TIMER0 Fixes ────────────────────────────────────────────────────


class TestTimer0Fixes:

    def test_prescaler_bitwidth_is_4(self, svd_root):
        timer = _find_peripheral(svd_root, "TIMER0")
        cr = _find_register(timer, "CR")
        prescaler = _find_field(cr, "PRESCALER")
        assert int(prescaler.find("bitWidth").text) == 4

    def test_prescaler_writeconstraint_max_is_15(self, svd_root):
        timer = _find_peripheral(svd_root, "TIMER0")
        cr = _find_register(timer, "CR")
        prescaler = _find_field(cr, "PRESCALER")
        wc_max = prescaler.find("writeConstraint/range/maximum")
        assert wc_max is not None
        assert int(wc_max.text) == 15

    def test_iclr_register_mwv_is_onetoset(self, svd_root):
        timer = _find_peripheral(svd_root, "TIMER0")
        iclr = _find_register(timer, "ICLR")
        mwv = iclr.find("modifiedWriteValues")
        assert mwv is not None
        assert mwv.text == "oneToSet"

    def test_iclr_field_overrides_preserved(self, svd_root):
        timer = _find_peripheral(svd_root, "TIMER0")
        iclr = _find_register(timer, "ICLR")
        cc_clr = _find_field(iclr, "CC_CLR")
        brk_clr = _find_field(iclr, "BRK_CLR")
        assert cc_clr.find("modifiedWriteValues").text == "zeroToSet"
        assert brk_clr.find("modifiedWriteValues").text == "zeroToToggle"

    def test_ccr_dim_is_3(self, svd_root):
        timer = _find_peripheral(svd_root, "TIMER0")
        ccr = _find_register(timer, "CCR%s")
        assert int(ccr.find("dim").text) == 3

    def test_ccr_dimindex_has_3_entries(self, svd_root):
        timer = _find_peripheral(svd_root, "TIMER0")
        ccr = _find_register(timer, "CCR%s")
        dim_idx = ccr.find("dimIndex").text
        entries = [e.strip() for e in dim_idx.split(",")]
        assert len(entries) == 3


# ── DMA Fixes ────────────────────────────────────────────────────────


class TestDMAFixes:

    def test_msize_bitwidth_is_3(self, svd_root):
        dma = _find_peripheral(svd_root, "DMA")
        s0cr = _find_register(dma, "S0CR")
        msize = _find_field(s0cr, "MSIZE")
        assert int(msize.find("bitWidth").text) == 3

    def test_alt_cfg_offset_is_0x18(self, svd_root):
        dma = _find_peripheral(svd_root, "DMA")
        alt_cfg = _find_register(dma, "ALT_CFG")
        offset = alt_cfg.find("addressOffset").text
        assert int(offset, 0) == 0x18

    def test_no_overlap_s0m0ar_alt_cfg(self, svd_root):
        dma = _find_peripheral(svd_root, "DMA")
        s0m0ar = _find_register(dma, "S0M0AR")
        alt_cfg = _find_register(dma, "ALT_CFG")
        off1 = int(s0m0ar.find("addressOffset").text, 0)
        off2 = int(alt_cfg.find("addressOffset").text, 0)
        assert off1 != off2


# ── GPIOA Fixes ──────────────────────────────────────────────────────


class TestGPIOAFixes:

    def test_odr_no_special_mwv(self, svd_root):
        gpioa = _find_peripheral(svd_root, "GPIOA")
        odr = _find_register(gpioa, "ODR")
        mwv = odr.find("modifiedWriteValues")
        if mwv is not None:
            assert mwv.text == "modify"

    def test_odr_fields_preserved(self, svd_root):
        gpioa = _find_peripheral(svd_root, "GPIOA")
        odr = _find_register(gpioa, "ODR")
        fields = odr.find("fields")
        found = any("OD" in f.find("name").text for f in fields if f.find("name") is not None)
        assert found


# ── GPIOB Fixes ──────────────────────────────────────────────────────


class TestGPIOBFixes:

    def test_gpiob_still_derived(self, svd_root):
        gpiob = _find_peripheral(svd_root, "GPIOB")
        assert gpiob.get("derivedFrom") == "GPIOA"

    def test_gpiob_has_lockr(self, svd_root):
        gpiob = _find_peripheral(svd_root, "GPIOB")
        lockr = _find_register(gpiob, "LOCKR")
        assert lockr is not None

    def test_gpiob_lockr_offset(self, svd_root):
        gpiob = _find_peripheral(svd_root, "GPIOB")
        lockr = _find_register(gpiob, "LOCKR")
        assert int(lockr.find("addressOffset").text, 0) == 0x1C

    def test_gpiob_lockr_has_lck_field(self, svd_root):
        gpiob = _find_peripheral(svd_root, "GPIOB")
        lockr = _find_register(gpiob, "LOCKR")
        lck = _find_field(lockr, "LCK")
        assert lck is not None
        assert int(lck.find("bitOffset").text) == 0
        assert int(lck.find("bitWidth").text) == 16

    def test_gpiob_lockr_has_lckk_field(self, svd_root):
        gpiob = _find_peripheral(svd_root, "GPIOB")
        lockr = _find_register(gpiob, "LOCKR")
        lckk = _find_field(lockr, "LCKK")
        assert lckk is not None
        assert int(lckk.find("bitOffset").text) == 16
        assert int(lckk.find("bitWidth").text) == 1


# ══════════════════════════════════════════════════════════════════════
# Codegen Audit Tests — evaluate the solver's error identification
# ══════════════════════════════════════════════════════════════════════


class TestCodegenAudit:
    """Verify the audit report correctly identifies errors in proposed_codegen.json."""

    def test_has_errors_key(self, audit):
        assert "errors" in audit
        assert isinstance(audit["errors"], list)

    def test_minimum_error_count(self, audit):
        """At least 8 distinct errors should be reported."""
        assert len(audit["errors"]) >= 8

    def test_each_error_has_required_fields(self, audit):
        for e in audit["errors"]:
            assert "category" in e, f"Error missing 'category': {e}"
            assert "location" in e, f"Error missing 'location': {e}"
            assert "explanation" in e, f"Error missing 'explanation': {e}"

    def _has_error(self, audit, category=None, location_keywords=None, explanation_keywords=None):
        """Check that a matching error entry exists."""
        for e in audit["errors"]:
            if category and e.get("category") != category:
                continue
            combined = (
                (e.get("location", "") or "").lower() + " " +
                (e.get("explanation", "") or "").lower() + " " +
                str(e.get("proposed_value", "")).lower() + " " +
                str(e.get("correct_value", "")).lower()
            )
            if location_keywords:
                if not any(kw.lower() in combined for kw in location_keywords):
                    continue
            if explanation_keywords:
                if not any(kw.lower() in combined for kw in explanation_keywords):
                    continue
            return True
        return False

    def test_timer0_cr_bitmap_error_reported(self, audit):
        """CR bitmap errors (wrong zero_to_modify and/or one_to_modify) must be identified."""
        assert self._has_error(
            audit, category="bitmap",
            location_keywords=["timer0", "cr"],
            explanation_keywords=["zero_to_modify", "one_to_modify", "bitmap", "sync", "prescaler", "mode"]
        )

    def test_timer0_iclr_bitmap_error_reported(self, audit):
        """ICLR bitmap error (field overrides ignored) must be identified."""
        assert self._has_error(
            audit, category="bitmap",
            location_keywords=["timer0", "iclr"],
            explanation_keywords=["override", "field", "cc_clr", "brk_clr", "zero", "inherit"]
        )

    def test_ccr_expansion_error_reported(self, audit):
        """CCR%s not expanded to individual registers must be identified."""
        assert self._has_error(
            audit, category="expansion",
            location_keywords=["ccr"],
            explanation_keywords=["expand", "individual", "array", "ccr0", "ccr1"]
        )

    def test_gpioa_odr_bitmap_error_reported(self, audit):
        """GPIOA.ODR bitmap error (register MWV ignored) must be identified."""
        assert self._has_error(
            audit, category="bitmap",
            location_keywords=["gpioa", "odr"],
            explanation_keywords=["onetotoggle", "register", "one_to_modify", "0xffff", "inherit"]
        )

    def test_dma_overlap_error_reported(self, audit):
        """DMA overlap between S0M0AR and ALT_CFG must be identified."""
        assert self._has_error(
            audit, category="overlap",
            location_keywords=["dma"],
            explanation_keywords=["s0m0ar", "alt_cfg", "0x14", "overlap"]
        )

    def test_mode_safety_error_reported(self, audit):
        """TIMER0.CR.MODE safety error (safe→unsafe) must be identified."""
        assert self._has_error(
            audit, category="safety",
            location_keywords=["mode"],
            explanation_keywords=["enum", "3", "4", "unsafe", "coverage"]
        )

    def test_dma_safety_errors_reported(self, audit):
        """At least one DMA field safety error (DIR/PSIZE/MSIZE) must be identified."""
        assert self._has_error(
            audit, category="safety",
            location_keywords=["dma", "s0cr"],
            explanation_keywords=["unsafe", "safe", "enum", "constraint"]
        )

    def test_gpiob_inheritance_error_reported(self, audit):
        """GPIOB empty derived_registers must be identified."""
        assert self._has_error(
            audit, category="inheritance",
            location_keywords=["gpiob"],
            explanation_keywords=["derived", "inherit", "moder", "odr", "empty"]
        )


# ══════════════════════════════════════════════════════════════════════
# Corrected Codegen Tests — verify analysis of the FIXED SVD
# ══════════════════════════════════════════════════════════════════════


class TestCorrectedCodegenBitmaps:
    """Verify write-effect bitmaps computed from the fixed SVD."""

    def test_has_bitmaps_key(self, corrected):
        assert "bitmaps" in corrected

    # -- TIMER0 --

    def test_timer0_cr_zero_to_modify(self, corrected):
        """SYNC_RST[19:16] is zeroToClear → zero_to_modify = 0x000F0000."""
        bm = corrected["bitmaps"]["TIMER0"]["CR"]
        assert _hex_val(bm["zero_to_modify"]) == 0x000F0000

    def test_timer0_cr_one_to_modify(self, corrected):
        """EN[0]=W1C + IRQ_CLR[11:8]=W1S + TOGGLE_BITS[27:24]=W1T → 0x0F000F01."""
        bm = corrected["bitmaps"]["TIMER0"]["CR"]
        assert _hex_val(bm["one_to_modify"]) == 0x0F000F01

    def test_timer0_arr_bitmaps_zero(self, corrected):
        bm = corrected["bitmaps"]["TIMER0"]["ARR"]
        assert _hex_val(bm["zero_to_modify"]) == 0
        assert _hex_val(bm["one_to_modify"]) == 0

    def test_timer0_iclr_zero_to_modify(self, corrected):
        """CC_CLR[2]=zeroToSet + BRK_CLR[3]=zeroToToggle → 0x0C."""
        bm = corrected["bitmaps"]["TIMER0"]["ICLR"]
        assert _hex_val(bm["zero_to_modify"]) == 0x0C

    def test_timer0_iclr_one_to_modify(self, corrected):
        """OVF_CLR[0]+UDF_CLR[1] inherit register oneToSet → 0x03."""
        bm = corrected["bitmaps"]["TIMER0"]["ICLR"]
        assert _hex_val(bm["one_to_modify"]) == 0x03

    def test_timer0_ccr_expanded(self, corrected):
        """CCR must be expanded to CCR0, CCR1, CCR2 (not CCR3, not CCR%s)."""
        timer_bm = corrected["bitmaps"]["TIMER0"]
        assert "CCR0" in timer_bm
        assert "CCR1" in timer_bm
        assert "CCR2" in timer_bm
        assert "CCR3" not in timer_bm
        assert "CCR%s" not in timer_bm

    def test_timer0_ccr0_bitmaps(self, corrected):
        """FLAGS[19:16]=W1S → one_to_modify = 0x000F0000."""
        bm = corrected["bitmaps"]["TIMER0"]["CCR0"]
        assert _hex_val(bm["zero_to_modify"]) == 0
        assert _hex_val(bm["one_to_modify"]) == 0x000F0000

    # -- DMA --

    def test_dma_s0cr_bitmaps_zero(self, corrected):
        """No MWV on any DMA.S0CR field → both bitmaps zero."""
        bm = corrected["bitmaps"]["DMA"]["S0CR"]
        assert _hex_val(bm["zero_to_modify"]) == 0
        assert _hex_val(bm["one_to_modify"]) == 0

    def test_dma_alt_cfg_bitmaps_zero(self, corrected):
        bm = corrected["bitmaps"]["DMA"]["ALT_CFG"]
        assert _hex_val(bm["zero_to_modify"]) == 0
        assert _hex_val(bm["one_to_modify"]) == 0

    # -- GPIOA --

    def test_gpioa_odr_bitmaps_zero_after_fix(self, corrected):
        """After removing oneToToggle MWV, ODR bitmaps should be zero."""
        bm = corrected["bitmaps"]["GPIOA"]["ODR"]
        assert _hex_val(bm["zero_to_modify"]) == 0
        assert _hex_val(bm["one_to_modify"]) == 0

    def test_gpioa_moder_bitmaps_zero(self, corrected):
        bm = corrected["bitmaps"]["GPIOA"]["MODER"]
        assert _hex_val(bm["zero_to_modify"]) == 0
        assert _hex_val(bm["one_to_modify"]) == 0

    # -- GPIOB (inherited + LOCKR) --

    def test_gpiob_has_bitmaps(self, corrected):
        """GPIOB should appear in bitmaps with resolved inherited registers."""
        assert "GPIOB" in corrected["bitmaps"]

    def test_gpiob_inherited_moder_bitmaps(self, corrected):
        bm = corrected["bitmaps"]["GPIOB"]["MODER"]
        assert _hex_val(bm["zero_to_modify"]) == 0
        assert _hex_val(bm["one_to_modify"]) == 0

    def test_gpiob_inherited_odr_bitmaps(self, corrected):
        bm = corrected["bitmaps"]["GPIOB"]["ODR"]
        assert _hex_val(bm["zero_to_modify"]) == 0
        assert _hex_val(bm["one_to_modify"]) == 0

    def test_gpiob_lockr_bitmaps(self, corrected):
        bm = corrected["bitmaps"]["GPIOB"]["LOCKR"]
        assert _hex_val(bm["zero_to_modify"]) == 0
        assert _hex_val(bm["one_to_modify"]) == 0


class TestCorrectedCodegenSafety:
    """Verify field safety classifications for the fixed SVD."""

    def test_has_field_safety_key(self, corrected):
        assert "field_safety" in corrected

    def test_timer0_cr_en_safe(self, corrected):
        """1-bit field → safe."""
        assert corrected["field_safety"]["TIMER0.CR.EN"] == "safe"

    def test_timer0_cr_mode_unsafe(self, corrected):
        """2-bit field, 3/4 enum values → unsafe."""
        assert corrected["field_safety"]["TIMER0.CR.MODE"] == "unsafe"

    def test_timer0_cr_prescaler_safe(self, corrected):
        """4-bit field, writeConstraint 0-15 covers full range → safe."""
        assert corrected["field_safety"]["TIMER0.CR.PRESCALER"] == "safe"

    def test_timer0_cr_irq_clr_unsafe(self, corrected):
        """4-bit field, no constraint, no enum → unsafe."""
        assert corrected["field_safety"]["TIMER0.CR.IRQ_CLR"] == "unsafe"

    def test_timer0_iclr_ovf_clr_safe(self, corrected):
        assert corrected["field_safety"]["TIMER0.ICLR.OVF_CLR"] == "safe"

    def test_dma_s0cr_dir_unsafe(self, corrected):
        """2-bit field, 3/4 enum values → unsafe."""
        assert corrected["field_safety"]["DMA.S0CR.DIR"] == "unsafe"

    def test_dma_s0cr_psize_unsafe(self, corrected):
        """2-bit field, 3/4 enum values → unsafe."""
        assert corrected["field_safety"]["DMA.S0CR.PSIZE"] == "unsafe"

    def test_dma_s0cr_msize_unsafe(self, corrected):
        """3-bit field, no constraint, no enum → unsafe."""
        assert corrected["field_safety"]["DMA.S0CR.MSIZE"] == "unsafe"

    def test_dma_alt_cfg_alt_mode_range(self, corrected):
        """3-bit field, writeConstraint 1-6 (partial) → range(1,6)."""
        assert corrected["field_safety"]["DMA.ALT_CFG.ALT_MODE"] == "range(1,6)"

    def test_gpioa_moder_mode_safe(self, corrected):
        """2-bit field, 4/4 enum values → safe."""
        val = corrected["field_safety"].get(
            "GPIOA.MODER.MODE%s",
            corrected["field_safety"].get("GPIOA.MODER.MODE0", None),
        )
        assert val == "safe"

    def test_gpiob_lockr_lck_unsafe(self, corrected):
        """16-bit field, no constraint → unsafe."""
        assert corrected["field_safety"]["GPIOB.LOCKR.LCK"] == "unsafe"

    def test_gpiob_lockr_lckk_safe(self, corrected):
        """1-bit field → safe."""
        assert corrected["field_safety"]["GPIOB.LOCKR.LCKK"] == "safe"


class TestCorrectedCodegenOverlaps:
    """Verify overlap detection in fixed SVD (no overlaps after fix)."""

    def test_has_overlaps_key(self, corrected):
        assert "overlaps" in corrected

    def test_timer0_no_overlaps(self, corrected):
        assert corrected["overlaps"]["TIMER0"] == []

    def test_dma_no_overlaps_after_fix(self, corrected):
        """After fixing ALT_CFG offset, DMA should have no overlaps."""
        assert corrected["overlaps"]["DMA"] == []

    def test_gpioa_no_overlaps(self, corrected):
        assert corrected["overlaps"]["GPIOA"] == []


class TestCorrectedCodegenInheritance:
    """Verify derived peripheral register resolution."""

    def test_has_derived_registers_key(self, corrected):
        assert "derived_registers" in corrected

    def test_gpiob_inherits_gpioa_plus_lockr(self, corrected):
        """GPIOB should resolve to GPIOA registers + LOCKR."""
        regs = corrected["derived_registers"]["GPIOB"]
        assert "MODER" in regs
        assert "ODR" in regs
        assert "BSRR" in regs
        assert "LOCKR" in regs

    def test_gpiob_derived_count(self, corrected):
        """GPIOB should have exactly 4 resolved registers."""
        assert len(corrected["derived_registers"]["GPIOB"]) == 4


# ══════════════════════════════════════════════════════════════════════
# Hazard Assessment Tests — verify write-hazard identification
# ══════════════════════════════════════════════════════════════════════


class TestHazardAssessment:
    """Verify the write-hazard analysis identifies correct registers."""

    def test_has_hazardous_registers_key(self, hazard):
        assert "hazardous_registers" in hazard
        assert isinstance(hazard["hazardous_registers"], list)

    def test_exactly_two_hazardous_registers(self, hazard):
        """Only TIMER0.CR and TIMER0.ICLR have mixed write-effect types."""
        assert len(hazard["hazardous_registers"]) == 2

    def _find_hazard(self, hazard, peripheral, register):
        for h in hazard["hazardous_registers"]:
            if h.get("peripheral") == peripheral and h.get("register") == register:
                return h
        return None

    def test_timer0_cr_is_hazardous(self, hazard):
        h = self._find_hazard(hazard, "TIMER0", "CR")
        assert h is not None, "TIMER0.CR should be identified as hazardous"

    def test_timer0_cr_write_effect_types(self, hazard):
        """CR has oneToClear, oneToSet, oneToToggle, zeroToClear."""
        h = self._find_hazard(hazard, "TIMER0", "CR")
        types = set(h["write_effect_types"])
        assert types == {"oneToClear", "oneToSet", "oneToToggle", "zeroToClear"}

    def test_timer0_cr_hazard_bitmaps(self, hazard):
        h = self._find_hazard(hazard, "TIMER0", "CR")
        assert _hex_val(h["zero_to_modify"]) == 0x000F0000
        assert _hex_val(h["one_to_modify"]) == 0x0F000F01

    def test_timer0_iclr_is_hazardous(self, hazard):
        h = self._find_hazard(hazard, "TIMER0", "ICLR")
        assert h is not None, "TIMER0.ICLR should be identified as hazardous"

    def test_timer0_iclr_write_effect_types(self, hazard):
        """ICLR has oneToSet (inherited), zeroToSet, zeroToToggle (overrides)."""
        h = self._find_hazard(hazard, "TIMER0", "ICLR")
        types = set(h["write_effect_types"])
        assert types == {"oneToSet", "zeroToSet", "zeroToToggle"}

    def test_timer0_iclr_hazard_bitmaps(self, hazard):
        h = self._find_hazard(hazard, "TIMER0", "ICLR")
        assert _hex_val(h["zero_to_modify"]) == 0x0C
        assert _hex_val(h["one_to_modify"]) == 0x03

    def test_no_false_positives(self, hazard):
        """Registers with 0 or 1 write-effect types should NOT be listed."""
        names = {(h["peripheral"], h["register"]) for h in hazard["hazardous_registers"]}
        # CCR has only oneToSet, not mixed
        assert ("TIMER0", "CCR0") not in names
        assert ("TIMER0", "CCR1") not in names
        # ARR has no write effects
        assert ("TIMER0", "ARR") not in names
        # DMA registers have no write effects
        assert ("DMA", "S0CR") not in names
        # GPIOA ODR has no write effects after fix
        assert ("GPIOA", "ODR") not in names
