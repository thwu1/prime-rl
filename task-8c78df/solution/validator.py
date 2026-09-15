#!/usr/bin/env python3
"""
RISC-V ISA Configuration Validator

Implements all validation rules from the Sail RISC-V formal model's
validate_config.sail, covering: privilege mode dependencies, virtual memory
hierarchy, XLEN-dependent restrictions, mutual exclusion groups, transitive
extension dependencies, vector extension constraints, PMP configuration,
and extension parameter constraints.
"""

import json
import math
import os
import sys


def ext(config, name):
    """Check if extension is supported in the configuration."""
    return config.get("extensions", {}).get(name, False)


def validate_config(config):
    """
    Validate a RISC-V ISA configuration against the Sail formal model rules.

    Args:
        config: dict with keys xlen, extensions, vector, pmp,
                cache_block_size_exp, reservation_set_size_exp

    Returns:
        dict with {"valid": bool, "violations": list[str]}
    """
    violations = []
    xlen = config["xlen"]
    vec = config.get("vector", {})
    pmp = config.get("pmp", {})
    vlen_exp = vec.get("vlen_exp", 7)
    elen_exp = vec.get("elen_exp", 6)
    max_index_eew_exp = vec.get("max_index_eew_exp", 6)

    # =========================================================================
    # check_privs(): S requires U
    # =========================================================================
    if ext(config, "S") and not ext(config, "U"):
        violations.append(
            "User mode (U) should be enabled if supervisor mode (S) is enabled."
        )

    # =========================================================================
    # check_mmu_config(): Virtual memory hierarchy and XLEN constraints
    # =========================================================================
    if xlen == 64:
        # S required for any Sv mode on RV64
        if not ext(config, "S") and (
            ext(config, "Sv57") or ext(config, "Sv48") or ext(config, "Sv39")
        ):
            violations.append(
                "Supervisor mode (S) disabled but one of (Sv57, Sv48, Sv39) is enabled: "
                "cannot support address translation without supervisor mode."
            )
        # Sv57 requires Sv48
        if ext(config, "Sv57") and not ext(config, "Sv48"):
            violations.append(
                "Sv57 is enabled but Sv48 is disabled: supporting Sv57 requires supporting Sv48."
            )
        # Sv48 requires Sv39
        if ext(config, "Sv48") and not ext(config, "Sv39"):
            violations.append(
                "Sv48 is enabled but Sv39 is disabled: supporting Sv48 requires supporting Sv39."
            )
        # Sv32 is RV32-only
        if ext(config, "Sv32"):
            violations.append("Sv32 is enabled: Sv32 is not supported on RV64.")
    else:
        # xlen == 32
        # S required for Sv32 on RV32
        if not ext(config, "S") and ext(config, "Sv32"):
            violations.append(
                "Supervisor mode (S) is disabled but Sv32 is enabled: "
                "cannot support address translation without supervisor mode."
            )
        # Sv39/48/57 are RV64-only
        if ext(config, "Sv39") or ext(config, "Sv48") or ext(config, "Sv57"):
            violations.append(
                "One or more of Sv39/Sv48/Sv57 is enabled: these are not supported on RV32."
            )

    # Helper: does this config have virtual memory support?
    has_vm = (xlen == 64 and ext(config, "Sv39")) or (
        xlen == 32 and ext(config, "Sv32")
    )

    # Svrsw60t59b: RV64-only, requires Sv39
    if ext(config, "Svrsw60t59b"):
        if xlen == 32:
            violations.append(
                "The Svrsw60t59b extension is enabled: Svrsw60t59b is not supported on RV32."
            )
        elif not ext(config, "Sv39"):
            violations.append(
                "The Svrsw60t59b extension is enabled but Sv39 is disabled: "
                "Svrsw60t59b depends on Sv39 on RV64."
            )

    # Ssccptr requires virtual memory
    if ext(config, "Ssccptr") and not has_vm:
        if xlen == 32:
            violations.append(
                "The Ssccptr extension is enabled but Sv32 is disabled: "
                "Ssccptr depends on Sv32 on RV32."
            )
        else:
            violations.append(
                "The Ssccptr extension is enabled but Sv39 is disabled: "
                "Ssccptr depends on Sv39 on RV64."
            )

    # Svade requires virtual memory
    if ext(config, "Svade") and not has_vm:
        if xlen == 32:
            violations.append(
                "The Svade extension is enabled but Sv32 is disabled: "
                "Svade depends on Sv32 on RV32."
            )
        else:
            violations.append(
                "The Svade extension is enabled but Sv39 is disabled: "
                "Svade depends on Sv39 on RV64."
            )

    # Svadu requires virtual memory
    if ext(config, "Svadu") and not has_vm:
        if xlen == 32:
            violations.append(
                "The Svadu extension is enabled but Sv32 is disabled: "
                "Svadu depends on Sv32 on RV32."
            )
        else:
            violations.append(
                "The Svadu extension is enabled but Sv39 is disabled: "
                "Svadu depends on Sv39 on RV64."
            )

    # Svpbmt: RV64-only, requires Sv39
    if ext(config, "Svpbmt"):
        if xlen == 32:
            violations.append(
                "The Svpbmt extension is enabled: Svpbmt is not supported on RV32."
            )
        elif not ext(config, "Sv39"):
            violations.append(
                "The Svpbmt extension is enabled but Sv39 is disabled: "
                "Svpbmt depends on Sv39 on RV64."
            )

    # Svnapot: RV64-only, requires Sv39
    if ext(config, "Svnapot"):
        if xlen == 32:
            violations.append(
                "The Svnapot extension is enabled: Svnapot is not supported on RV32."
            )
        elif not ext(config, "Sv39"):
            violations.append(
                "The Svnapot extension is enabled but Sv39 is disabled: "
                "Svnapot depends on Sv39 on RV64."
            )

    # Svvptc requires virtual memory
    if ext(config, "Svvptc") and not has_vm:
        if xlen == 32:
            violations.append(
                "The Svvptc extension is enabled but Sv32 is disabled: "
                "Svvptc depends on Sv32 on RV32."
            )
        else:
            violations.append(
                "The Svvptc extension is enabled but Sv39 is disabled: "
                "Svvptc depends on Sv39 on RV64."
            )

    # =========================================================================
    # check_vlen_elen(): VLEN and ELEN range and relationship
    # =========================================================================
    if vlen_exp < elen_exp:
        violations.append(
            f"VLEN (set to 2^{vlen_exp}) cannot be less than ELEN (set to 2^{elen_exp})."
        )
    if vlen_exp < 3 or vlen_exp > 16:
        violations.append(
            f"VLEN set to 2^{vlen_exp} but must be within [2^3, 2^16]."
        )
    if elen_exp < 3 or elen_exp > 16:
        violations.append(
            f"ELEN set to 2^{elen_exp} but must be within [2^3, 2^16]."
        )

    # =========================================================================
    # check_vext_config(): Vector extension constraints
    # =========================================================================

    # Derive vector_support_level from enabled extensions
    # Full > Float_double > Float_single > Integer > Disabled
    if ext(config, "V"):
        vector_support_level = 4  # Full
    elif ext(config, "Zve64d"):
        vector_support_level = 3  # Float_double
    elif ext(config, "Zve32f") or ext(config, "Zve64f"):
        vector_support_level = 2  # Float_single
    elif ext(config, "Zve32x") or ext(config, "Zve64x"):
        vector_support_level = 1  # Integer
    else:
        vector_support_level = 0  # Disabled

    # Integer level: ELEN >= 2^5
    if vector_support_level >= 1 and elen_exp < 5:
        violations.append(
            f"Zve*x is enabled but ELEN is 2^{elen_exp}: ELEN must be >= 2^5."
        )

    # max_index_eew checks (always checked when any vector ext is present)
    if vector_support_level >= 1:
        if max_index_eew_exp > elen_exp:
            violations.append(
                f"The maximum index EEW is 2^{max_index_eew_exp} but ELEN is "
                f"2^{elen_exp}: the index EEW must not exceed ELEN."
            )
        elif max_index_eew_exp < 3:
            violations.append(
                f"The maximum index EEW is 2^{max_index_eew_exp} but it should "
                f"be at least 2^3."
            )

    # Float_single level: requires F
    if vector_support_level >= 2 and not ext(config, "F"):
        violations.append(
            "Zve*f is enabled but F is disabled: supporting Zve*f requires F."
        )

    # Float_double level: requires D and ELEN >= 2^6
    if vector_support_level >= 3:
        if elen_exp < 6:
            violations.append(
                f"Zve*d is enabled but ELEN is 2^{elen_exp}: ELEN must be >= 2^6."
            )
        if not ext(config, "D"):
            violations.append(
                "Zve*d is enabled but D is disabled: supporting Zve*d requires D."
            )

    # Zve32x: requires Zicsr and Zvl32b (vlen_exp >= 5)
    if ext(config, "Zve32x"):
        if not ext(config, "Zicsr"):
            violations.append(
                "Zve32x is enabled but Zicsr is disabled: supporting Zve32x requires Zicsr."
            )
        if vlen_exp < 5:  # Zvl32b
            violations.append(
                f"VLEN (set to 2^{vlen_exp}) is below the minimum required for "
                f"Zve32x (need Zvl32b)."
            )

    # Zve64x: requires Zvl64b (vlen_exp >= 6)
    if ext(config, "Zve64x"):
        if vlen_exp < 6:  # Zvl64b
            violations.append(
                f"VLEN (set to 2^{vlen_exp}) is below the minimum required for "
                f"Zve64x (need Zvl64b)."
            )

    # V (Full): requires Zvl128b (vlen_exp >= 7)
    if vector_support_level >= 4:
        if vlen_exp < 7:  # Zvl128b
            violations.append(
                f"VLEN (set to 2^{vlen_exp}) is below the minimum required for "
                f"V (need Zvl128b)."
            )

    # Zvfhmin requires Zve32f
    if ext(config, "Zvfhmin") and not ext(config, "Zve32f"):
        violations.append(
            "Zvfhmin is enabled but Zve32f is disabled: Zvfhmin requires Zve32f."
        )

    # Zvfh requires Zve32f and Zfhmin
    if ext(config, "Zvfh"):
        if not ext(config, "Zve32f") or not ext(config, "Zfhmin"):
            violations.append(
                "Zvfh is enabled but Zve32f and/or Zfhmin are disabled: "
                "Zvfh requires Zve32f and Zfhmin."
            )

    # Vector crypto extensions requiring Zve32x
    for zvext in ["Zvbb", "Zvkb", "Zvkg", "Zvkned", "Zvknha", "Zvksed", "Zvksh", "Zvkt"]:
        if ext(config, zvext) and not ext(config, "Zve32x"):
            violations.append(
                f"{zvext} is enabled but Zve32x is disabled: {zvext} requires Zve32x."
            )

    # Vector crypto extensions requiring Zve64x or V
    for zvext in ["Zvbc", "Zvknhb"]:
        if ext(config, zvext) and not (ext(config, "Zve64x") or ext(config, "V")):
            violations.append(
                f"{zvext} is enabled but Zve64x and V are disabled: "
                f"{zvext} requires Zve64x or V."
            )

    # =========================================================================
    # check_pmp(): PMP configuration
    # =========================================================================
    if pmp.get("na4_supported", False) and pmp.get("grain", 0) != 0:
        violations.append(
            "NA4 is not supported if the PMP grain G is non-zero."
        )
    if pmp.get("usable_count", 0) > pmp.get("count", 0):
        violations.append(
            "The number of usable PMP entries cannot exceed the total number of PMP entries."
        )

    # =========================================================================
    # check_misc_extension_dependencies()
    # =========================================================================

    # Zcf is RV32-only
    if ext(config, "Zcf") and xlen == 64:
        violations.append(
            "The Zcf extension is enabled: Zcf is not supported on RV64."
        )

    # F and Zfinx are mutually exclusive
    if ext(config, "F") and ext(config, "Zfinx"):
        violations.append(
            "The F and Zfinx extensions are mutually exclusive and cannot be "
            "supported simultaneously."
        )

    # Zabha requires Zaamo or A
    if ext(config, "Zabha") and not (ext(config, "Zaamo") or ext(config, "A")):
        violations.append(
            "The Zabha extension is enabled but Zaamo and A are disabled: "
            "supporting Zabha requires Zaamo or A."
        )

    # Zacas requires Zaamo or A
    if ext(config, "Zacas") and not (ext(config, "Zaamo") or ext(config, "A")):
        violations.append(
            "The Zacas extension is enabled but Zaamo and A are disabled: "
            "supporting Zacas requires Zaamo or A."
        )

    # Zfinx requires Zicsr
    if ext(config, "Zfinx") and not ext(config, "Zicsr"):
        violations.append(
            "The Zfinx extension is enabled but Zicsr is disabled: "
            "supporting Zfinx requires Zicsr."
        )

    # Zdinx requires Zfinx
    if ext(config, "Zdinx") and not ext(config, "Zfinx"):
        violations.append(
            "The Zdinx extension is enabled but Zfinx is disabled: "
            "supporting Zdinx requires Zfinx."
        )

    # Zhinx requires Zfinx
    if ext(config, "Zhinx") and not ext(config, "Zfinx"):
        violations.append(
            "The Zhinx extension is enabled but Zfinx is disabled: "
            "supporting Zhinx requires Zfinx."
        )

    # Zhinxmin requires Zfinx
    if ext(config, "Zhinxmin") and not ext(config, "Zfinx"):
        violations.append(
            "The Zhinxmin extension is enabled but Zfinx is disabled: "
            "supporting Zhinxmin requires Zfinx."
        )

    # Zicfilp requires Zicsr
    if ext(config, "Zicfilp") and not ext(config, "Zicsr"):
        violations.append(
            "The Zicfilp extension is enabled but Zicsr is disabled: "
            "supporting Zicfilp requires Zicsr."
        )

    # Zicfiss requires Zicsr, Zimop, and (Zaamo or A)
    if ext(config, "Zicfiss"):
        if not (
            ext(config, "Zicsr")
            and ext(config, "Zimop")
            and (ext(config, "Zaamo") or ext(config, "A"))
        ):
            missing = []
            if not ext(config, "Zicsr"):
                missing.append("Zicsr")
            if not ext(config, "Zimop"):
                missing.append("Zimop")
            if not (ext(config, "Zaamo") or ext(config, "A")):
                missing.append("Zaamo or A")
            violations.append(
                f"The Zicfiss extension is enabled but one or more of "
                f"{', '.join(missing)} are disabled: supporting Zicfiss requires "
                f"Zicsr, Zimop and (Zaamo or A)."
            )

    # Zfbfmin requires F
    if ext(config, "Zfbfmin") and not ext(config, "F"):
        violations.append(
            "The Zfbfmin extension is enabled but F is disabled: "
            "supporting Zfbfmin requires F."
        )

    # Zvfbfmin requires Zve32f
    if ext(config, "Zvfbfmin") and not ext(config, "Zve32f"):
        violations.append(
            "The Zvfbfmin extension is enabled but Zve32f is disabled: "
            "supporting Zvfbfmin requires Zve32f."
        )

    # Zvfbfwma requires Zfbfmin and Zvfbfmin
    if ext(config, "Zvfbfwma"):
        if not ext(config, "Zfbfmin"):
            violations.append(
                "The Zvfbfwma extension is enabled but Zfbfmin is disabled: "
                "supporting Zvfbfwma requires Zfbfmin."
            )
        if not ext(config, "Zvfbfmin"):
            violations.append(
                "The Zvfbfwma extension is enabled but Zvfbfmin is disabled: "
                "supporting Zvfbfwma requires Zvfbfmin."
            )

    # Ssqosid requires Zicsr
    if ext(config, "Ssqosid") and not ext(config, "Zicsr"):
        violations.append(
            "The Ssqosid extension is enabled but Zicsr is disabled: "
            "supporting Ssqosid requires Zicsr."
        )

    # =========================================================================
    # check_extension_param_constraints()
    # =========================================================================

    # Zic64b requires cache block size of 64 bytes (exp == 6)
    if ext(config, "Zic64b") and config.get("cache_block_size_exp", 6) != 6:
        violations.append(
            "The Zic64b extension is enabled but the cache block size is not 64 bytes."
        )

    # A or Zalrsc: reservation set size must be >= xlen/8
    if ext(config, "A") or ext(config, "Zalrsc"):
        log2_xlen = int(math.log2(xlen))  # 5 for RV32, 6 for RV64
        min_rss_exp = log2_xlen - 3
        rss_exp = config.get("reservation_set_size_exp", 3)
        if rss_exp < min_rss_exp:
            violations.append(
                f"The A or Zalrsc extensions are enabled, but the reservation set "
                f"size of 2^{rss_exp} is too small; it should be at least "
                f"2^{min_rss_exp} for the LR/SC operands on this platform."
            )

    return {"valid": len(violations) == 0, "violations": violations}


def main():
    configs_dir = "/app/configs"
    results_dir = "/app/results"
    os.makedirs(results_dir, exist_ok=True)

    for fname in sorted(os.listdir(configs_dir)):
        if not fname.endswith(".json"):
            continue
        config_name = fname[:-5]
        with open(os.path.join(configs_dir, fname)) as f:
            config = json.load(f)

        result = validate_config(config)
        result["config"] = config_name

        with open(os.path.join(results_dir, fname), "w") as f:
            json.dump(result, f, indent=2)

        status = "VALID" if result["valid"] else "INVALID"
        print(f"{config_name}: {status}")
        if result["violations"]:
            for v in result["violations"]:
                print(f"  - {v}")


if __name__ == "__main__":
    main()
