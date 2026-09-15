#!/usr/bin/env python3

"""
RISC-V Sail Formal Model Configuration Auditor and Repairer.

Extracts constraint rules from the Sail RISC-V formal model's
validate_config.sail and extensions.sail, validates hardware configs,
and produces corrected configs + structured audit report.
"""

import json
import os
import copy


def load_config(path):
    with open(path) as f:
        return json.load(f)


def save_config(config, path):
    with open(path, "w") as f:
        json.dump(config, f, indent=2)


def ext_supported(config, name):
    exts = config.get("extensions", {})
    ext = exts.get(name, {})
    if isinstance(ext, dict):
        return ext.get("supported", False)
    return False


def set_ext(config, name, val):
    if name not in config["extensions"]:
        config["extensions"][name] = {}
    config["extensions"][name]["supported"] = val


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


def derives_zve32x(config):
    return v_is_configured(config) and get_elen_exp(config) >= 5 and support_level_idx(config) >= 1


def derives_zve32f(config):
    return v_is_configured(config) and get_elen_exp(config) >= 5 and support_level_idx(config) >= 2


def derives_zve64x(config):
    return v_is_configured(config) and get_elen_exp(config) >= 6 and support_level_idx(config) >= 1


def derives_v_full(config):
    return v_is_configured(config) and get_vlen_exp(config) >= 7 and support_level_idx(config) >= 4


ATOMIC_ORDER = {"AMONone": 0, "AMOSwap": 1, "AMOLogical": 2, "AMOArithmetic": 3, "AMOCASQ": 4}


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

def validate(config):
    v = []
    xlen = get_xlen(config)

    # --- check_privs ---
    if ext_supported(config, "S") and not ext_supported(config, "U"):
        v.append("S_REQUIRES_U")

    # --- check_mmu_config ---
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

    has_vmem = sv32 if xlen == 32 else sv39

    if ext_supported(config, "Svrsw60t59b"):
        if xlen == 32:
            v.append("SVRSW60T59B_NOT_RV32")
        elif not sv39:
            v.append("SVRSW60T59B_REQUIRES_SV39")

    if ext_supported(config, "Ssccptr") and not has_vmem:
        v.append("SSCCPTR_REQUIRES_VMEM")
    if ext_supported(config, "Svade") and not has_vmem:
        v.append("SVADE_REQUIRES_VMEM")
    if ext_supported(config, "Svadu") and not has_vmem:
        v.append("SVADU_REQUIRES_VMEM")

    if ext_supported(config, "Svpbmt"):
        if xlen == 32:
            v.append("SVPBMT_NOT_RV32")
        elif not sv39:
            v.append("SVPBMT_REQUIRES_SV39")

    if ext_supported(config, "Svnapot"):
        if xlen == 32:
            v.append("SVNAPOT_NOT_RV32")
        elif not sv39:
            v.append("SVNAPOT_REQUIRES_SV39")

    if ext_supported(config, "Svvptc") and not has_vmem:
        v.append("SVVPTC_REQUIRES_VMEM")

    # --- check_vlen_elen ---
    if v_is_configured(config):
        vlen = get_vlen_exp(config)
        elen = get_elen_exp(config)
        if vlen < elen:
            v.append("VLEN_LT_ELEN")
        if vlen < 3 or vlen > 16:
            v.append("VLEN_RANGE")
        if elen < 3 or elen > 16:
            v.append("ELEN_RANGE")

    # --- check_vext_config ---
    if v_is_configured(config):
        sl_idx = support_level_idx(config)
        vlen = get_vlen_exp(config)
        elen = get_elen_exp(config)
        vext = config["extensions"]["V"]
        max_idx_eew = vext.get("max_index_eew_exp", 3)

        if sl_idx >= 1 and elen < 5:
            v.append("VEXT_INTEGER_ELEN")
        if max_idx_eew > elen:
            v.append("MAX_INDEX_EEW_EXCEEDS_ELEN")
        if max_idx_eew < 3:
            v.append("MAX_INDEX_EEW_MIN")
        if sl_idx >= 2 and not ext_supported(config, "F"):
            v.append("VEXT_FLOAT_REQUIRES_F")
        if sl_idx >= 3:
            if elen < 6:
                v.append("VEXT_DOUBLE_ELEN")
            if not ext_supported(config, "D"):
                v.append("VEXT_DOUBLE_REQUIRES_D")

        if derives_zve32x(config) and not ext_supported(config, "Zicsr"):
            v.append("ZVE32X_REQUIRES_ZICSR")
        if derives_zve32x(config) and vlen < 5:
            v.append("ZVE32X_REQUIRES_ZVL32B")
        if derives_zve64x(config) and vlen < 6:
            v.append("ZVE64X_REQUIRES_ZVL64B")
        if derives_v_full(config) and vlen < 7:
            v.append("V_FULL_REQUIRES_ZVL128B")

        if ext_supported(config, "Zvfhmin") and not derives_zve32f(config):
            v.append("ZVFHMIN_REQUIRES_ZVE32F")
        if ext_supported(config, "Zvfh"):
            if not derives_zve32f(config) or not ext_supported(config, "Zfhmin"):
                v.append("ZVFH_REQUIRES_ZVE32F_ZFHMIN")

        for ext in ["Zvbb", "Zvkb", "Zvkg", "Zvkned", "Zvknha", "Zvksed", "Zvksh", "Zvkt"]:
            if ext_supported(config, ext) and not derives_zve32x(config):
                v.append(f"{ext.upper()}_REQUIRES_ZVE32X")

        if ext_supported(config, "Zvbc") and not (derives_zve64x(config) or derives_v_full(config)):
            v.append("ZVBC_REQUIRES_ZVE64X_V")
        if ext_supported(config, "Zvknhb") and not (derives_zve64x(config) or derives_v_full(config)):
            v.append("ZVKNHB_REQUIRES_ZVE64X_V")

    # --- check_pmp ---
    pmp = config.get("memory", {}).get("pmp", {})
    if pmp.get("NA4_supported", False) and pmp.get("grain", 0) != 0:
        v.append("PMP_NA4_GRAIN")
    if pmp.get("usable_count", 0) > pmp.get("count", 0):
        v.append("PMP_USABLE_LE_COUNT")

    # --- check_pma_regions ---
    regions = config.get("memory", {}).get("regions", [])
    ziccamoa = ext_supported(config, "Ziccamoa")
    ziccamoc = ext_supported(config, "Ziccamoc")
    ziccif = ext_supported(config, "Ziccif")
    zicclsm_ext = ext_supported(config, "Zicclsm")
    ziccrse = ext_supported(config, "Ziccrse")
    ssccptr_ext = ext_supported(config, "Ssccptr")
    svadu_ext = ext_supported(config, "Svadu")
    found_svadu_pma = False

    for i, r in enumerate(regions):
        base = int(r["base"], 16)
        size = int(r["size"], 16)
        mt = r.get("mem_type", "")

        if base % 0x1000 != 0:
            v.append(f"REGION_ALIGN_BASE_{i}")
        if size % 0x1000 != 0:
            v.append(f"REGION_ALIGN_SIZE_{i}")

        if mt == "MainMemory":
            for attr in ("readable", "writable", "read_idempotent", "write_idempotent"):
                if not r.get(attr, False):
                    v.append(f"MAIN_MEM_{attr.upper()}_{i}")

        is_cc_main = mt == "MainMemory" and r.get("cacheable", False) and r.get("coherent", False)
        if is_cc_main:
            al = ATOMIC_ORDER.get(r.get("atomic_support", "AMONone"), 0)
            if ziccamoa and al < ATOMIC_ORDER["AMOArithmetic"]:
                v.append(f"ZICCAMOA_PMA_{i}")
            if ziccamoc and r.get("atomic_support") != "AMOCASQ":
                v.append(f"ZICCAMOC_PMA_{i}")
            if ziccif and not r.get("executable", False):
                v.append(f"ZICCIF_PMA_{i}")
            if ziccrse and r.get("reservability", "RsrvNone") != "RsrvEventual":
                v.append(f"ZICCRSE_PMA_{i}")
            if ssccptr_ext and not r.get("supports_pte_read", False):
                v.append(f"SSCCPTR_PMA_{i}")

        if r.get("supports_pte_write", False) and r.get("reservability") == "RsrvEventual":
            found_svadu_pma = True

    if svadu_ext and not found_svadu_pma:
        v.append("SVADU_NO_PTE_WRITE_REGION")

    for i in range(len(regions) - 1):
        bi = int(regions[i]["base"], 16)
        si = int(regions[i]["size"], 16)
        bn = int(regions[i + 1]["base"], 16)
        if bi + si > bn:
            v.append(f"REGIONS_OVERLAP_{i}")

    # --- check_misc_extension_deps ---
    if ext_supported(config, "Zcf") and xlen == 64:
        v.append("ZCF_RV32_ONLY")
    if ext_supported(config, "F") and ext_supported(config, "Zfinx"):
        v.append("F_ZFINX_EXCLUSIVE")
    if ext_supported(config, "Zabha") and not (ext_supported(config, "Zaamo") or ext_supported(config, "A")):
        v.append("ZABHA_REQUIRES_ZAAMO")
    if ext_supported(config, "Zacas") and not (ext_supported(config, "Zaamo") or ext_supported(config, "A")):
        v.append("ZACAS_REQUIRES_ZAAMO")
    if ext_supported(config, "Zfinx") and not ext_supported(config, "Zicsr"):
        v.append("ZFINX_REQUIRES_ZICSR")
    if ext_supported(config, "Zdinx") and not ext_supported(config, "Zfinx"):
        v.append("ZDINX_REQUIRES_ZFINX")
    if ext_supported(config, "Zhinx") and not ext_supported(config, "Zfinx"):
        v.append("ZHINX_REQUIRES_ZFINX")
    if ext_supported(config, "Zhinxmin") and not ext_supported(config, "Zfinx"):
        v.append("ZHINXMIN_REQUIRES_ZFINX")
    if ext_supported(config, "Zicfilp") and not ext_supported(config, "Zicsr"):
        v.append("ZICFILP_REQUIRES_ZICSR")
    if ext_supported(config, "Zicfiss"):
        ok = (ext_supported(config, "Zicsr")
              and ext_supported(config, "Zimop")
              and (ext_supported(config, "Zaamo") or ext_supported(config, "A")))
        if not ok:
            v.append("ZICFISS_REQUIRES_DEPS")
    if ext_supported(config, "Zfbfmin") and not ext_supported(config, "F"):
        v.append("ZFBFMIN_REQUIRES_F")
    if ext_supported(config, "Zvfbfmin") and not derives_zve32f(config):
        v.append("ZVFBFMIN_REQUIRES_ZVE32F")
    if ext_supported(config, "Zvfbfwma"):
        if not ext_supported(config, "Zfbfmin") or not ext_supported(config, "Zvfbfmin"):
            v.append("ZVFBFWMA_REQUIRES_DEPS")

    if ext_supported(config, "Sstvala"):
        if not ext_supported(config, "S"):
            v.append("SSTVALA_REQUIRES_S")
        xtval = config.get("base", {}).get("xtval_nonzero", {})
        for key, tag in [
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
        ]:
            if not xtval.get(key, False):
                v.append(tag)

    if ext_supported(config, "Ssqosid") and not ext_supported(config, "Zicsr"):
        v.append("SSQOSID_REQUIRES_ZICSR")

    # --- check_extension_param_constraints ---
    if ext_supported(config, "Zic64b"):
        if config.get("platform", {}).get("cache_block_size_exp", 6) != 6:
            v.append("ZIC64B_CACHE_BLOCK")

    min_rsv = 3 if xlen == 64 else 2
    if ext_supported(config, "A") or ext_supported(config, "Zalrsc"):
        if config.get("platform", {}).get("reservation_set_size_exp", min_rsv) < min_rsv:
            v.append("RESERVATION_SIZE")

    if ext_supported(config, "Zicclsm"):
        mis = config.get("memory", {}).get("misaligned", {}).get("exceptions", {})
        if mis.get("load_store", "None") == "AccessFault":
            v.append("ZICCLSM_GLOBAL_LS")
        if mis.get("vector", "None") == "AccessFault":
            v.append("ZICCLSM_GLOBAL_VEC")

    # --- check_stateen ---
    stateen = config.get("extensions", {}).get("Stateen", {})
    sm = stateen.get("Smstateen", {}).get("supported", False) if isinstance(stateen.get("Smstateen"), dict) else False
    ss = stateen.get("Ssstateen", {}).get("supported", False) if isinstance(stateen.get("Ssstateen"), dict) else False
    if sm or ss:
        se0_ro = stateen.get("SE0_readonly_zero", False)
        c_ro = stateen.get("C_readonly_zero", True)
        if se0_ro and (ext_supported(config, "Zfinx") or not c_ro):
            v.append("STATEEN_SE0_WRITABLE")

    return v


# ---------------------------------------------------------------------------
# Fixer
# ---------------------------------------------------------------------------

def fix_config(config):
    config = copy.deepcopy(config)
    xlen = get_xlen(config)

    for _ in range(50):
        viols = set(validate(config))
        if not viols:
            break

        # --- Privilege ---
        if "S_REQUIRES_U" in viols:
            set_ext(config, "U", True)

        # --- MMU ---
        if "SV_REQUIRES_S" in viols:
            set_ext(config, "S", True)
        if "SV32_REQUIRES_S" in viols:
            set_ext(config, "S", True)
        if "SV48_REQUIRES_SV39" in viols:
            set_ext(config, "Sv39", True)
        if "SV57_REQUIRES_SV48" in viols:
            set_ext(config, "Sv48", True)
        if "SV32_NOT_RV64" in viols:
            set_ext(config, "Sv32", False)
        if "SV39_48_57_NOT_RV32" in viols:
            for m in ("Sv39", "Sv48", "Sv57"):
                set_ext(config, m, False)

        # VM extension deps: enable Sv39 on RV64
        for tag in ("SVRSW60T59B_REQUIRES_SV39", "SVPBMT_REQUIRES_SV39",
                     "SVNAPOT_REQUIRES_SV39", "SSCCPTR_REQUIRES_VMEM",
                     "SVADE_REQUIRES_VMEM", "SVADU_REQUIRES_VMEM",
                     "SVVPTC_REQUIRES_VMEM"):
            if tag in viols and xlen == 64:
                set_ext(config, "Sv39", True)
                set_ext(config, "S", True)

        # RV32-only extension errors
        for tag in ("SVRSW60T59B_NOT_RV32", "SVPBMT_NOT_RV32", "SVNAPOT_NOT_RV32"):
            ext_name = tag.split("_NOT_RV32")[0]
            if tag in viols:
                set_ext(config, ext_name.capitalize(), False)

        # --- F/Zfinx exclusivity ---
        if "F_ZFINX_EXCLUSIVE" in viols:
            if ext_supported(config, "D") or support_level_idx(config) >= 2:
                set_ext(config, "Zfinx", False)
                set_ext(config, "Zdinx", False)
                set_ext(config, "Zhinx", False)
                set_ext(config, "Zhinxmin", False)
            else:
                set_ext(config, "Zfinx", False)

        # --- Extension deps ---
        if "ZVE32X_REQUIRES_ZICSR" in viols or "ZICFILP_REQUIRES_ZICSR" in viols or "SSQOSID_REQUIRES_ZICSR" in viols or "ZFINX_REQUIRES_ZICSR" in viols:
            set_ext(config, "Zicsr", True)

        if "ZICFISS_REQUIRES_DEPS" in viols:
            set_ext(config, "Zicsr", True)
            set_ext(config, "Zimop", True)
            if not ext_supported(config, "Zaamo") and not ext_supported(config, "A"):
                set_ext(config, "Zaamo", True)

        if "ZABHA_REQUIRES_ZAAMO" in viols or "ZACAS_REQUIRES_ZAAMO" in viols:
            set_ext(config, "Zaamo", True)

        if "ZDINX_REQUIRES_ZFINX" in viols or "ZHINX_REQUIRES_ZFINX" in viols or "ZHINXMIN_REQUIRES_ZFINX" in viols:
            if ext_supported(config, "F"):
                set_ext(config, "Zdinx", False)
                set_ext(config, "Zhinx", False)
                set_ext(config, "Zhinxmin", False)
            else:
                set_ext(config, "Zfinx", True)

        if "ZFBFMIN_REQUIRES_F" in viols:
            set_ext(config, "F", True)

        if "ZCF_RV32_ONLY" in viols:
            set_ext(config, "Zcf", False)

        # --- Vector fixes ---
        if "VEXT_DOUBLE_REQUIRES_D" in viols:
            set_ext(config, "D", True)
            set_ext(config, "F", True)

        if "VEXT_FLOAT_REQUIRES_F" in viols:
            set_ext(config, "F", True)

        if v_is_configured(config):
            vext = config["extensions"]["V"]
            elen = vext.get("elen_exp", 3)
            vlen = vext.get("vlen_exp", 3)
            sl_idx = support_level_idx(config)

            if "VEXT_DOUBLE_ELEN" in viols:
                elen = max(elen, 6)
                vext["elen_exp"] = elen

            if "VEXT_INTEGER_ELEN" in viols:
                elen = max(elen, 5)
                vext["elen_exp"] = elen

            if "MAX_INDEX_EEW_EXCEEDS_ELEN" in viols:
                miee = vext.get("max_index_eew_exp", 3)
                if miee > elen:
                    vext["max_index_eew_exp"] = elen

            if "MAX_INDEX_EEW_MIN" in viols:
                vext["max_index_eew_exp"] = max(vext.get("max_index_eew_exp", 3), 3)

            if "VLEN_LT_ELEN" in viols:
                vext["vlen_exp"] = max(vext["vlen_exp"], vext["elen_exp"])

            if vext.get("vlen_exp", 3) < 3:
                vext["vlen_exp"] = 3
            if vext.get("elen_exp", 3) < 3:
                vext["elen_exp"] = 3

        # --- PMP ---
        if "PMP_NA4_GRAIN" in viols:
            config["memory"]["pmp"]["grain"] = 0

        if "PMP_USABLE_LE_COUNT" in viols:
            pmp = config["memory"]["pmp"]
            pmp["usable_count"] = pmp["count"]

        # --- PMA region fixes ---
        regions = config.get("memory", {}).get("regions", [])
        for i, r in enumerate(regions):
            base = int(r["base"], 16)
            size = int(r["size"], 16)
            if base % 0x1000 != 0:
                r["base"] = hex(base & ~0xFFF)
            if size % 0x1000 != 0:
                r["size"] = hex((size + 0xFFF) & ~0xFFF)

            mt = r.get("mem_type", "")
            if mt == "MainMemory":
                r["readable"] = True
                r["writable"] = True
                r["read_idempotent"] = True
                r["write_idempotent"] = True

            is_cc_main = mt == "MainMemory" and r.get("cacheable", False) and r.get("coherent", False)
            if is_cc_main:
                if f"ZICCAMOA_PMA_{i}" in viols or f"ZICCAMOC_PMA_{i}" in viols:
                    r["atomic_support"] = "AMOCASQ"
                if f"ZICCIF_PMA_{i}" in viols:
                    r["executable"] = True
                if f"ZICCRSE_PMA_{i}" in viols:
                    r["reservability"] = "RsrvEventual"
                if f"SSCCPTR_PMA_{i}" in viols:
                    r["supports_pte_read"] = True

        if "SVADU_NO_PTE_WRITE_REGION" in viols:
            for r in regions:
                if r.get("mem_type") == "MainMemory":
                    r["supports_pte_write"] = True
                    r["reservability"] = "RsrvEventual"
                    break

        # Sort regions
        regions.sort(key=lambda r: int(r["base"], 16))
        for i in range(len(regions) - 1):
            bi = int(regions[i]["base"], 16)
            si = int(regions[i]["size"], 16)
            bn = int(regions[i + 1]["base"], 16)
            if bi + si > bn:
                ns = bn - bi
                regions[i]["size"] = hex(max(ns, 0x1000))

        # --- Platform ---
        if "ZIC64B_CACHE_BLOCK" in viols:
            config["platform"]["cache_block_size_exp"] = 6

        if "RESERVATION_SIZE" in viols:
            min_rsv = 3 if xlen == 64 else 2
            config["platform"]["reservation_set_size_exp"] = min_rsv

        # --- Zicclsm global ---
        if "ZICCLSM_GLOBAL_LS" in viols or "ZICCLSM_GLOBAL_VEC" in viols:
            mis = config.setdefault("memory", {}).setdefault("misaligned", {}).setdefault("exceptions", {})
            mis["load_store"] = "None"
            mis["vector"] = "None"

        # --- Sstvala ---
        if ext_supported(config, "Sstvala"):
            if "SSTVALA_REQUIRES_S" in viols:
                set_ext(config, "S", True)
            xtval = config.setdefault("base", {}).setdefault("xtval_nonzero", {})
            for key in ["load_page_fault", "load_access_fault", "misaligned_load",
                        "samo_page_fault", "samo_access_fault", "misaligned_samo",
                        "fetch_page_fault", "fetch_access_fault", "misaligned_fetch",
                        "hardware_breakpoint", "illegal_instruction"]:
                tag = f"SSTVALA_{key.upper().replace('_FAULT', '_FAULT').replace('MISALIGNED_', 'MISALIGNED_')}"
                # Just set all to True if any Sstvala violation exists
                xtval[key] = True

        # --- Stateen ---
        if "STATEEN_SE0_WRITABLE" in viols:
            stateen = config["extensions"].get("Stateen", {})
            stateen["SE0_readonly_zero"] = False

    return config


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    configs_dir = "/app/configs"
    output_dir = "/app/output"
    os.makedirs(output_dir, exist_ok=True)

    audit = {}

    for fname in sorted(os.listdir(configs_dir)):
        if not fname.endswith(".json"):
            continue

        config = load_config(os.path.join(configs_dir, fname))
        violations = validate(config)

        print(f"\n{fname}: {len(violations)} violation(s)")
        for viol in violations:
            print(f"  - {viol}")

        fixed = fix_config(config)
        remaining = validate(fixed)
        print(f"  After fix: {len(remaining)} remaining")
        for viol in remaining:
            print(f"    ! {viol}")

        save_config(fixed, os.path.join(output_dir, fname))

        audit[fname] = {
            "violations": violations,
            "num_violations": len(violations),
        }

    with open("/app/audit.json", "w") as f:
        json.dump(audit, f, indent=2)
    print(f"\nAudit written to /app/audit.json")


if __name__ == "__main__":
    main()
