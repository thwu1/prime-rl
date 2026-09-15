
"""
Ground-truth validator for RISC-V configuration constraints derived from
the Sail RISC-V formal model's validate_config.sail and extensions.sail.
"""

import json
import os
import pytest

CONFIG_NAMES = [
    "vector_crypto.json",
    "coherent_server.json",
    "cfi_platform.json",
    "bf16_vmem.json",
]


def load_config(path):
    with open(path) as f:
        return json.load(f)


def ext_supported(config, name):
    exts = config.get("extensions", {})
    ext = exts.get(name, {})
    if isinstance(ext, dict):
        return ext.get("supported", False)
    return False


def get_xlen(config):
    return config["base"]["xlen"]


def get_vlen_exp(config):
    v = config.get("extensions", {}).get("V", {})
    if isinstance(v, dict) and v.get("supported", False):
        return v.get("vlen_exp", 3)
    return 3


def get_elen_exp(config):
    v = config.get("extensions", {}).get("V", {})
    if isinstance(v, dict) and v.get("supported", False):
        return v.get("elen_exp", 3)
    return 3


SUPPORT_LEVELS = ["Disabled", "Integer", "Float_single", "Float_double", "Full"]


def support_level_idx(config):
    v = config.get("extensions", {}).get("V", {})
    if not isinstance(v, dict) or not v.get("supported", False):
        return 0
    sl = v.get("support_level", "Disabled")
    return SUPPORT_LEVELS.index(sl) if sl in SUPPORT_LEVELS else 0


def v_is_configured(config):
    v = config.get("extensions", {}).get("V", {})
    return isinstance(v, dict) and v.get("supported", False)


# Derived extension support (from extensions.sail hartSupports definitions)
def derives_zve32x(config):
    return v_is_configured(config) and get_elen_exp(config) >= 5 and support_level_idx(config) >= 1


def derives_zve32f(config):
    return v_is_configured(config) and get_elen_exp(config) >= 5 and support_level_idx(config) >= 2


def derives_zve64x(config):
    return v_is_configured(config) and get_elen_exp(config) >= 6 and support_level_idx(config) >= 1


def derives_zve64d(config):
    return v_is_configured(config) and get_elen_exp(config) >= 6 and support_level_idx(config) >= 3


def derives_zvl32b(config):
    return v_is_configured(config) and get_vlen_exp(config) >= 5


def derives_zvl64b(config):
    return v_is_configured(config) and get_vlen_exp(config) >= 6


def derives_zvl128b(config):
    return v_is_configured(config) and get_vlen_exp(config) >= 7


def derives_v_full(config):
    return v_is_configured(config) and get_vlen_exp(config) >= 7 and support_level_idx(config) >= 4


ATOMIC_ORDER = {"AMONone": 0, "AMOSwap": 1, "AMOLogical": 2, "AMOArithmetic": 3, "AMOCASQ": 4}


# ---------------------------------------------------------------------------
# Constraint checking — each returns list of violation strings
# ---------------------------------------------------------------------------

def check_privs(config):
    v = []
    if ext_supported(config, "S") and not ext_supported(config, "U"):
        v.append("S_REQUIRES_U")
    return v


def check_mmu_config(config):
    v = []
    xlen = get_xlen(config)
    sv32 = ext_supported(config, "Sv32")
    sv39 = ext_supported(config, "Sv39")
    sv48 = ext_supported(config, "Sv48")
    sv57 = ext_supported(config, "Sv57")

    if xlen == 64:
        if not ext_supported(config, "S") and (sv57 or sv48 or sv39):
            v.append("SV_REQUIRES_S")
        if sv57 and not sv48:
            v.append("SV57_REQUIRES_SV48")
        if sv48 and not sv39:
            v.append("SV48_REQUIRES_SV39")
        if sv32:
            v.append("SV32_NOT_RV64")
    else:
        if not ext_supported(config, "S") and sv32:
            v.append("SV32_REQUIRES_S")
        if sv39 or sv48 or sv57:
            v.append("SV39_48_57_NOT_RV32")

    # Virtual memory extension dependencies
    def has_virtual_memory():
        if xlen == 32:
            return sv32
        return sv39

    # Svrsw60t59b: RV64 only, requires Sv39
    if ext_supported(config, "Svrsw60t59b"):
        if xlen == 32:
            v.append("SVRSW60T59B_NOT_RV32")
        elif not sv39:
            v.append("SVRSW60T59B_REQUIRES_SV39")

    # Ssccptr requires virtual memory
    if ext_supported(config, "Ssccptr") and not has_virtual_memory():
        v.append("SSCCPTR_REQUIRES_VMEM")

    # Svade requires virtual memory
    if ext_supported(config, "Svade") and not has_virtual_memory():
        v.append("SVADE_REQUIRES_VMEM")

    # Svadu requires virtual memory
    if ext_supported(config, "Svadu") and not has_virtual_memory():
        v.append("SVADU_REQUIRES_VMEM")

    # Svpbmt: RV64 only, requires Sv39
    if ext_supported(config, "Svpbmt"):
        if xlen == 32:
            v.append("SVPBMT_NOT_RV32")
        elif not sv39:
            v.append("SVPBMT_REQUIRES_SV39")

    # Svnapot: RV64 only, requires Sv39
    if ext_supported(config, "Svnapot"):
        if xlen == 32:
            v.append("SVNAPOT_NOT_RV32")
        elif not sv39:
            v.append("SVNAPOT_REQUIRES_SV39")

    # Svvptc requires virtual memory
    if ext_supported(config, "Svvptc") and not has_virtual_memory():
        v.append("SVVPTC_REQUIRES_VMEM")

    return v


def check_vlen_elen(config):
    v = []
    if not v_is_configured(config):
        return v
    vlen = get_vlen_exp(config)
    elen = get_elen_exp(config)
    if vlen < elen:
        v.append("VLEN_LT_ELEN")
    if vlen < 3 or vlen > 16:
        v.append("VLEN_RANGE")
    if elen < 3 or elen > 16:
        v.append("ELEN_RANGE")
    return v


def check_vext_config(config):
    v = []
    if not v_is_configured(config):
        return v

    sl_idx = support_level_idx(config)
    vlen = get_vlen_exp(config)
    elen = get_elen_exp(config)
    vext = config["extensions"]["V"]
    max_idx_eew = vext.get("max_index_eew_exp", 3)

    # Integer level: elen >= 5
    if sl_idx >= 1 and elen < 5:
        v.append("VEXT_INTEGER_ELEN")

    # max_index_eew_exp checks
    if max_idx_eew > elen:
        v.append("MAX_INDEX_EEW_EXCEEDS_ELEN")
    if max_idx_eew < 3:
        v.append("MAX_INDEX_EEW_MIN")

    # Float_single requires F
    if sl_idx >= 2 and not ext_supported(config, "F"):
        v.append("VEXT_FLOAT_REQUIRES_F")

    # Float_double: elen >= 6 and D
    if sl_idx >= 3:
        if elen < 6:
            v.append("VEXT_DOUBLE_ELEN")
        if not ext_supported(config, "D"):
            v.append("VEXT_DOUBLE_REQUIRES_D")

    # Zve32x derived => requires Zicsr
    if derives_zve32x(config) and not ext_supported(config, "Zicsr"):
        v.append("ZVE32X_REQUIRES_ZICSR")

    # Zve32x derived => requires Zvl32b (vlen >= 5)
    if derives_zve32x(config) and not derives_zvl32b(config):
        v.append("ZVE32X_REQUIRES_ZVL32B")

    # Zve64x derived => requires Zvl64b (vlen >= 6)
    if derives_zve64x(config) and not derives_zvl64b(config):
        v.append("ZVE64X_REQUIRES_ZVL64B")

    # V Full => requires Zvl128b (vlen >= 7)
    if derives_v_full(config) and not derives_zvl128b(config):
        v.append("V_FULL_REQUIRES_ZVL128B")

    # Zvfhmin requires Zve32f
    if ext_supported(config, "Zvfhmin") and not derives_zve32f(config):
        v.append("ZVFHMIN_REQUIRES_ZVE32F")

    # Zvfh requires Zve32f and Zfhmin
    if ext_supported(config, "Zvfh"):
        if not derives_zve32f(config) or not ext_supported(config, "Zfhmin"):
            v.append("ZVFH_REQUIRES_ZVE32F_ZFHMIN")

    # Vector crypto extensions
    zve32x_deps = ["Zvbb", "Zvkb", "Zvkg", "Zvkned", "Zvknha", "Zvksed", "Zvksh", "Zvkt"]
    for ext in zve32x_deps:
        if ext_supported(config, ext) and not derives_zve32x(config):
            v.append(f"{ext.upper()}_REQUIRES_ZVE32X")

    # Zvbc and Zvknhb require Zve64x or V
    if ext_supported(config, "Zvbc") and not (derives_zve64x(config) or derives_v_full(config)):
        v.append("ZVBC_REQUIRES_ZVE64X_V")

    if ext_supported(config, "Zvknhb") and not (derives_zve64x(config) or derives_v_full(config)):
        v.append("ZVKNHB_REQUIRES_ZVE64X_V")

    return v


def check_pmp(config):
    v = []
    pmp = config.get("memory", {}).get("pmp", {})
    na4 = pmp.get("NA4_supported", False)
    grain = pmp.get("grain", 0)
    count = pmp.get("count", 0)
    usable = pmp.get("usable_count", 0)

    if na4 and grain != 0:
        v.append("PMP_NA4_GRAIN")
    if usable > count:
        v.append("PMP_USABLE_LE_COUNT")
    return v


def check_pma_regions(config):
    v = []
    regions = config.get("memory", {}).get("regions", [])

    # Build check options from extensions
    ziccamoa = ext_supported(config, "Ziccamoa")
    ziccamoc = ext_supported(config, "Ziccamoc")
    ziccif = ext_supported(config, "Ziccif")
    zicclsm = ext_supported(config, "Zicclsm")
    ziccrse = ext_supported(config, "Ziccrse")
    ssccptr = ext_supported(config, "Ssccptr")
    svadu = ext_supported(config, "Svadu")

    found_svadu_pma = False

    for i, r in enumerate(regions):
        base = int(r["base"], 16)
        size = int(r["size"], 16)
        mem_type = r.get("mem_type", "")

        # Page alignment
        if base % 0x1000 != 0:
            v.append(f"REGION_ALIGN_BASE_{i}")
        if size % 0x1000 != 0:
            v.append(f"REGION_ALIGN_SIZE_{i}")

        # MainMemory PMA requirements
        if mem_type == "MainMemory":
            if not r.get("readable", False):
                v.append(f"MAIN_MEM_READABLE_{i}")
            if not r.get("writable", False):
                v.append(f"MAIN_MEM_WRITABLE_{i}")
            if not r.get("read_idempotent", False):
                v.append(f"MAIN_MEM_READ_IDEMP_{i}")
            if not r.get("write_idempotent", False):
                v.append(f"MAIN_MEM_WRITE_IDEMP_{i}")

        # Coherent cacheable main memory PMA checks
        is_cc_main = (mem_type == "MainMemory"
                      and r.get("cacheable", False)
                      and r.get("coherent", False))

        if is_cc_main:
            atomic = r.get("atomic_support", "AMONone")
            atomic_level = ATOMIC_ORDER.get(atomic, 0)

            if ziccamoa and atomic_level < ATOMIC_ORDER["AMOArithmetic"]:
                v.append(f"ZICCAMOA_PMA_{i}")

            if ziccamoc and atomic != "AMOCASQ":
                v.append(f"ZICCAMOC_PMA_{i}")

            if ziccif and not r.get("executable", False):
                v.append(f"ZICCIF_PMA_{i}")

            if ziccrse and r.get("reservability", "RsrvNone") != "RsrvEventual":
                v.append(f"ZICCRSE_PMA_{i}")

            if ssccptr and not r.get("supports_pte_read", False):
                v.append(f"SSCCPTR_PMA_{i}")

        # Svadu: track if any region supports pte_write + RsrvEventual
        if r.get("supports_pte_write", False) and r.get("reservability") == "RsrvEventual":
            found_svadu_pma = True

    # Svadu existential check
    if svadu and not found_svadu_pma:
        v.append("SVADU_NO_PTE_WRITE_REGION")

    # Sorted and non-overlapping
    for i in range(len(regions) - 1):
        b_i = int(regions[i]["base"], 16)
        s_i = int(regions[i]["size"], 16)
        b_next = int(regions[i + 1]["base"], 16)
        if b_i + s_i > b_next:
            v.append(f"REGIONS_OVERLAP_{i}")

    return v


def check_misc_extension_deps(config):
    v = []
    xlen = get_xlen(config)

    # Zcf RV32 only
    if ext_supported(config, "Zcf") and xlen == 64:
        v.append("ZCF_RV32_ONLY")

    # F / Zfinx mutually exclusive
    if ext_supported(config, "F") and ext_supported(config, "Zfinx"):
        v.append("F_ZFINX_EXCLUSIVE")

    # Zabha requires Zaamo or A
    if ext_supported(config, "Zabha") and not (ext_supported(config, "Zaamo") or ext_supported(config, "A")):
        v.append("ZABHA_REQUIRES_ZAAMO")

    # Zacas requires Zaamo or A
    if ext_supported(config, "Zacas") and not (ext_supported(config, "Zaamo") or ext_supported(config, "A")):
        v.append("ZACAS_REQUIRES_ZAAMO")

    # Zfinx requires Zicsr
    if ext_supported(config, "Zfinx") and not ext_supported(config, "Zicsr"):
        v.append("ZFINX_REQUIRES_ZICSR")

    # Zdinx requires Zfinx
    if ext_supported(config, "Zdinx") and not ext_supported(config, "Zfinx"):
        v.append("ZDINX_REQUIRES_ZFINX")

    # Zhinx requires Zfinx
    if ext_supported(config, "Zhinx") and not ext_supported(config, "Zfinx"):
        v.append("ZHINX_REQUIRES_ZFINX")

    # Zhinxmin requires Zfinx
    if ext_supported(config, "Zhinxmin") and not ext_supported(config, "Zfinx"):
        v.append("ZHINXMIN_REQUIRES_ZFINX")

    # Zicfilp requires Zicsr
    if ext_supported(config, "Zicfilp") and not ext_supported(config, "Zicsr"):
        v.append("ZICFILP_REQUIRES_ZICSR")

    # Zicfiss requires Zicsr AND Zimop AND (Zaamo or A)
    if ext_supported(config, "Zicfiss"):
        zicsr_ok = ext_supported(config, "Zicsr")
        zimop_ok = ext_supported(config, "Zimop")
        atomic_ok = ext_supported(config, "Zaamo") or ext_supported(config, "A")
        if not (zicsr_ok and zimop_ok and atomic_ok):
            v.append("ZICFISS_REQUIRES_DEPS")

    # Zfbfmin requires F
    if ext_supported(config, "Zfbfmin") and not ext_supported(config, "F"):
        v.append("ZFBFMIN_REQUIRES_F")

    # Zvfbfmin requires Zve32f
    if ext_supported(config, "Zvfbfmin") and not derives_zve32f(config):
        v.append("ZVFBFMIN_REQUIRES_ZVE32F")

    # Zvfbfwma requires Zfbfmin and Zvfbfmin
    if ext_supported(config, "Zvfbfwma"):
        if not ext_supported(config, "Zfbfmin") or not ext_supported(config, "Zvfbfmin"):
            v.append("ZVFBFWMA_REQUIRES_DEPS")

    # Sstvala checks
    if ext_supported(config, "Sstvala"):
        if not ext_supported(config, "S"):
            v.append("SSTVALA_REQUIRES_S")
        xtval = config.get("base", {}).get("xtval_nonzero", {})
        xtval_checks = [
            ("load_page_fault", "SSTVALA_LOAD_PAGE_FAULT"),
            ("load_access_fault", "SSTVALA_LOAD_ACCESS_FAULT"),
            ("misaligned_load", "SSTVALA_MISALIGNED_LOAD"),
            ("samo_page_fault", "SSTVALA_SAMO_PAGE_FAULT"),
            ("samo_access_fault", "SSTVALA_SAMO_ACCESS_FAULT"),
            ("misaligned_samo", "SSTVALA_MISALIGNED_SAMO"),
            ("fetch_page_fault", "SSTVALA_FETCH_PAGE_FAULT"),
            ("fetch_access_fault", "SSTVALA_FETCH_ACCESS_FAULT"),
            ("misaligned_fetch", "SSTVALA_MISALIGNED_FETCH"),
            ("hardware_breakpoint", "SSTVALA_HW_BREAKPOINT"),
            ("illegal_instruction", "SSTVALA_ILLEGAL_INSTR"),
        ]
        for key, viol_id in xtval_checks:
            if not xtval.get(key, False):
                v.append(viol_id)

    # Ssqosid requires Zicsr
    if ext_supported(config, "Ssqosid") and not ext_supported(config, "Zicsr"):
        v.append("SSQOSID_REQUIRES_ZICSR")

    return v


def check_extension_param_constraints(config):
    v = []
    xlen = get_xlen(config)

    # Zic64b => cache_block_size_exp == 6
    if ext_supported(config, "Zic64b"):
        cbs = config.get("platform", {}).get("cache_block_size_exp", 6)
        if cbs != 6:
            v.append("ZIC64B_CACHE_BLOCK")

    # A or Zalrsc => reservation_set_size_exp >= min
    min_rsv = 3 if xlen == 64 else 2
    if ext_supported(config, "A") or ext_supported(config, "Zalrsc"):
        rss = config.get("platform", {}).get("reservation_set_size_exp", min_rsv)
        if rss < min_rsv:
            v.append("RESERVATION_SIZE")

    # Zicclsm: global misaligned exceptions must not be AccessFault
    if ext_supported(config, "Zicclsm"):
        misaligned = config.get("memory", {}).get("misaligned", {}).get("exceptions", {})
        ls = misaligned.get("load_store", "None")
        vec = misaligned.get("vector", "None")
        if ls == "AccessFault":
            v.append("ZICCLSM_GLOBAL_LS")
        if vec == "AccessFault":
            v.append("ZICCLSM_GLOBAL_VEC")

    return v


def check_stateen(config):
    v = []
    stateen = config.get("extensions", {}).get("Stateen", {})
    sm = stateen.get("Smstateen", {}).get("supported", False) if isinstance(stateen.get("Smstateen"), dict) else False
    ss = stateen.get("Ssstateen", {}).get("supported", False) if isinstance(stateen.get("Ssstateen"), dict) else False

    if not sm and not ss:
        return v

    se0_ro = stateen.get("SE0_readonly_zero", False)
    c_ro = stateen.get("C_readonly_zero", True)

    # SE0_readonly_zero + (Zfinx or !C_readonly_zero)
    if se0_ro and (ext_supported(config, "Zfinx") or not c_ro):
        v.append("STATEEN_SE0_WRITABLE")

    return v


def validate_all(config):
    violations = []
    violations.extend(check_privs(config))
    violations.extend(check_mmu_config(config))
    violations.extend(check_vlen_elen(config))
    violations.extend(check_vext_config(config))
    violations.extend(check_pmp(config))
    violations.extend(check_pma_regions(config))
    violations.extend(check_misc_extension_deps(config))
    violations.extend(check_extension_param_constraints(config))
    violations.extend(check_stateen(config))
    return violations


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOutputConfigsExist:
    @pytest.mark.parametrize("config_name", CONFIG_NAMES)
    def test_output_exists(self, config_name):
        path = f"/app/output/{config_name}"
        assert os.path.exists(path), f"Missing output: {path}"

    @pytest.mark.parametrize("config_name", CONFIG_NAMES)
    def test_valid_json(self, config_name):
        config = load_config(f"/app/output/{config_name}")
        assert isinstance(config, dict)


class TestOutputConfigSchema:
    @pytest.mark.parametrize("config_name", CONFIG_NAMES)
    def test_has_required_sections(self, config_name):
        config = load_config(f"/app/output/{config_name}")
        assert "base" in config
        assert "xlen" in config["base"]
        assert config["base"]["xlen"] in (32, 64)
        assert "extensions" in config
        assert "memory" in config
        assert "platform" in config


class TestOutputConfigsValid:
    @pytest.mark.parametrize("config_name", CONFIG_NAMES)
    def test_no_violations(self, config_name):
        config = load_config(f"/app/output/{config_name}")
        violations = validate_all(config)
        assert violations == [], (
            f"{config_name} has {len(violations)} violations: {violations}"
        )


class TestOriginalConfigsBroken:
    @pytest.mark.parametrize("config_name,min_violations", [
        ("vector_crypto.json", 5),
        ("coherent_server.json", 5),
        ("cfi_platform.json", 6),
        ("bf16_vmem.json", 7),
    ])
    def test_original_has_violations(self, config_name, min_violations):
        config = load_config(f"/app/configs/{config_name}")
        violations = validate_all(config)
        assert len(violations) >= min_violations, (
            f"Expected >= {min_violations} violations in {config_name}, "
            f"got {len(violations)}: {violations}"
        )


class TestConfigIntegrity:
    @pytest.mark.parametrize("config_name", CONFIG_NAMES)
    def test_xlen_preserved(self, config_name):
        original = load_config(f"/app/configs/{config_name}")
        corrected = load_config(f"/app/output/{config_name}")
        assert original["base"]["xlen"] == corrected["base"]["xlen"]

    def test_vector_crypto_preserves_vector(self):
        config = load_config("/app/output/vector_crypto.json")
        v = config["extensions"]["V"]
        assert v.get("supported", False), "V must remain enabled"
        sl = v.get("support_level", "Disabled")
        assert sl == "Float_double", "V support_level must remain Float_double"

    def test_vector_crypto_preserves_crypto(self):
        config = load_config("/app/output/vector_crypto.json")
        for ext in ["Zvbc", "Zvkg", "Zvkned", "Zvknhb"]:
            assert ext_supported(config, ext), f"{ext} must remain enabled"

    def test_coherent_server_preserves_coherence_exts(self):
        config = load_config("/app/output/coherent_server.json")
        for ext in ["Ziccamoa", "Ziccamoc", "Ziccif", "Ziccrse", "Ssccptr", "Svadu"]:
            assert ext_supported(config, ext), f"{ext} must remain enabled"

    def test_cfi_platform_preserves_cfi(self):
        config = load_config("/app/output/cfi_platform.json")
        assert ext_supported(config, "Zicfilp"), "Zicfilp must remain enabled"
        assert ext_supported(config, "Zicfiss"), "Zicfiss must remain enabled"
        assert ext_supported(config, "Sstvala"), "Sstvala must remain enabled"

    def test_bf16_vmem_preserves_bf16(self):
        config = load_config("/app/output/bf16_vmem.json")
        assert ext_supported(config, "Zfbfmin"), "Zfbfmin must remain enabled"
        assert ext_supported(config, "Zvfbfmin"), "Zvfbfmin must remain enabled"
        assert ext_supported(config, "Zvfbfwma"), "Zvfbfwma must remain enabled"

    def test_bf16_vmem_preserves_vmem_exts(self):
        config = load_config("/app/output/bf16_vmem.json")
        for ext in ["Svpbmt", "Svnapot", "Svrsw60t59b"]:
            assert ext_supported(config, ext), f"{ext} must remain enabled"


class TestAuditReport:
    def test_audit_exists(self):
        assert os.path.exists("/app/audit.json"), "audit.json missing"

    def test_audit_structure(self):
        with open("/app/audit.json") as f:
            audit = json.load(f)
        for name in CONFIG_NAMES:
            assert name in audit, f"{name} missing from audit"
            entry = audit[name]
            assert "violations" in entry, f"violations missing for {name}"
            assert isinstance(entry["violations"], list)
            assert "num_violations" in entry
            assert entry["num_violations"] == len(entry["violations"])

    @pytest.mark.parametrize("config_name,min_violations", [
        ("vector_crypto.json", 5),
        ("coherent_server.json", 5),
        ("cfi_platform.json", 6),
        ("bf16_vmem.json", 7),
    ])
    def test_audit_violation_counts(self, config_name, min_violations):
        with open("/app/audit.json") as f:
            audit = json.load(f)
        entry = audit[config_name]
        assert entry["num_violations"] >= min_violations, (
            f"Audit for {config_name}: expected >= {min_violations} violations, "
            f"got {entry['num_violations']}"
        )
