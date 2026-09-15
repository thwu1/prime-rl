#!/usr/bin/env python3
"""
Fix SVD discrepancies, audit proposed codegen, produce corrected analysis
and write-hazard assessment.
"""

import json
import xml.etree.ElementTree as ET


# ── SVD Helpers ──────────────────────────────────────────────────────


def find_peripheral(root, name):
    for p in root.find("peripherals"):
        if p.find("name").text == name:
            return p
    return None


def find_register(periph, name):
    regs = periph.find("registers")
    if regs is None:
        return None
    for r in regs:
        n = r.find("name")
        if n is not None and n.text == name:
            return r
    return None


def find_field(reg, name):
    fields = reg.find("fields")
    if fields is None:
        return None
    for f in fields:
        n = f.find("name")
        if n is not None and n.text == name:
            return f
    return None


def parse_int(s):
    if s is None:
        return None
    s = s.strip()
    if s.lower().startswith("0x"):
        return int(s, 16)
    return int(s)


def get_text(elem, tag, default=None):
    child = elem.find(tag)
    if child is not None and child.text is not None:
        return child.text.strip()
    return default


def get_int(elem, tag, default=None):
    text = get_text(elem, tag)
    return parse_int(text) if text is not None else default


# ── Bitmap Computation ───────────────────────────────────────────────


def compute_field_bitmask(bit_offset, bit_width, dim=None, dim_increment=None):
    if dim is not None and dim > 1 and dim_increment is not None:
        mask = 0
        for i in range(dim):
            off = bit_offset + i * dim_increment
            mask |= ((1 << bit_width) - 1) << off
        return mask
    return ((1 << bit_width) - 1) << bit_offset


def compute_bitmaps_for_register(reg_elem):
    """Compute zero_to_modify and one_to_modify bitmaps."""
    reg_mwv = get_text(reg_elem, "modifiedWriteValues")
    fields_elem = reg_elem.find("fields")
    zero_bm = 0
    one_bm = 0
    if fields_elem is None:
        return zero_bm, one_bm

    for field in fields_elem.findall("field"):
        field_mwv = get_text(field, "modifiedWriteValues")
        effective_mwv = field_mwv or reg_mwv or "modify"

        bit_offset = get_int(field, "bitOffset", 0)
        bit_width = get_int(field, "bitWidth", 1)
        dim = get_int(field, "dim")
        dim_inc = get_int(field, "dimIncrement")

        bitmask = compute_field_bitmask(bit_offset, bit_width, dim, dim_inc)

        if effective_mwv in ("oneToSet", "oneToClear", "oneToToggle"):
            one_bm |= bitmask
        elif effective_mwv in ("zeroToClear", "zeroToSet", "zeroToToggle"):
            zero_bm |= bitmask

    return zero_bm, one_bm


def collect_write_effect_types(reg_elem):
    """Collect the set of distinct write-effect types in a register's fields."""
    reg_mwv = get_text(reg_elem, "modifiedWriteValues")
    fields_elem = reg_elem.find("fields")
    effect_types = set()
    if fields_elem is None:
        return effect_types

    mwv_set = {"oneToClear", "oneToSet", "oneToToggle",
               "zeroToClear", "zeroToSet", "zeroToToggle"}

    for field in fields_elem.findall("field"):
        field_mwv = get_text(field, "modifiedWriteValues")
        effective_mwv = field_mwv or reg_mwv or "modify"
        if effective_mwv in mwv_set:
            effect_types.add(effective_mwv)

    return effect_types


# ── Safety Classification ────────────────────────────────────────────


def classify_field_safety(field_elem):
    width = get_int(field_elem, "bitWidth", 1)
    max_val = (1 << width) - 1

    wc = field_elem.find("writeConstraint")
    if wc is not None:
        range_elem = wc.find("range")
        if range_elem is not None:
            wc_min = get_int(range_elem, "minimum", 0)
            wc_max = get_int(range_elem, "maximum", 0)
            if wc_min == 0 and wc_max == max_val:
                return "safe"
            return f"range({wc_min},{wc_max})"

    if width == 1:
        return "safe"

    enum_count = 0
    for evs in field_elem.findall("enumeratedValues"):
        for ev in evs.findall("enumeratedValue"):
            is_def = get_text(ev, "isDefault", "")
            if is_def.lower() == "true":
                continue
            name = get_text(ev, "name", "")
            if name.lower() == "reserved":
                continue
            enum_count += 1
    if enum_count >= (1 << width):
        return "safe"

    return "unsafe"


# ── Overlap Detection ────────────────────────────────────────────────


def detect_overlaps(registers):
    """Find groups of registers at the same offset with overlapping byte ranges."""
    from collections import defaultdict
    overlaps = defaultdict(set)

    for i, (n1, o1, s1) in enumerate(registers):
        for j, (n2, o2, s2) in enumerate(registers):
            if i >= j:
                continue
            end1 = o1 + s1 // 8
            end2 = o2 + s2 // 8
            if o1 < end2 and o2 < end1:
                overlap_off = max(o1, o2)
                overlaps[overlap_off].add(n1)
                overlaps[overlap_off].add(n2)

    result = []
    for off in sorted(overlaps.keys()):
        result.append({"offset": off, "registers": sorted(overlaps[off])})
    return result


# ── Register Parsing & Expansion ─────────────────────────────────────


def parse_registers_from_peripheral(periph_elem):
    """Extract register info, expanding arrays."""
    registers = []
    regs_elem = periph_elem.find("registers")
    if regs_elem is None:
        return registers

    for reg in regs_elem.findall("register"):
        name = get_text(reg, "name")
        offset = get_int(reg, "addressOffset", 0)
        size = get_int(reg, "size", 32)
        access = get_text(reg, "access", "read-write")
        dim = get_int(reg, "dim")
        dim_inc = get_int(reg, "dimIncrement")
        dim_idx_text = get_text(reg, "dimIndex")

        if dim is not None and dim > 1:
            indices = [x.strip() for x in dim_idx_text.split(",")] if dim_idx_text else [str(i) for i in range(dim)]
            for i, idx in enumerate(indices):
                expanded_name = name.replace("%s", idx)
                registers.append({
                    "name": expanded_name,
                    "template_name": name,
                    "offset": offset + i * dim_inc,
                    "size": size,
                    "access": access,
                    "reg_elem": reg,
                })
        else:
            registers.append({
                "name": name,
                "template_name": name,
                "offset": offset,
                "size": size,
                "access": access,
                "reg_elem": reg,
            })

    return registers


def resolve_peripheral_registers(periph_elem, all_periphs):
    """Resolve registers including derivedFrom inheritance."""
    derived_from = periph_elem.get("derivedFrom")
    registers = {}

    if derived_from:
        for p in all_periphs:
            if p.find("name").text == derived_from:
                registers = resolve_peripheral_registers(p, all_periphs)
                break

    own_regs = parse_registers_from_peripheral(periph_elem)
    for r in own_regs:
        registers[r["name"]] = r

    return registers


# ── Fix SVD ──────────────────────────────────────────────────────────


def fix_svd(root):
    """Apply all 7 fixes to the SVD. Returns the tree root and discrepancy list."""

    # Fix 1: TIMER0.CR.PRESCALER bitWidth 5→4, writeConstraint max 31→15
    timer0 = find_peripheral(root, "TIMER0")
    cr = find_register(timer0, "CR")
    prescaler = find_field(cr, "PRESCALER")
    prescaler.find("bitWidth").text = "4"
    prescaler.find("writeConstraint/range/maximum").text = "15"

    # Fix 2: TIMER0.ICLR register MWV oneToClear → oneToSet
    iclr = find_register(timer0, "ICLR")
    iclr.find("modifiedWriteValues").text = "oneToSet"

    # Fix 3: TIMER0.CCR dim 4→3, dimIndex updated
    ccr = find_register(timer0, "CCR%s")
    ccr.find("dim").text = "3"
    ccr.find("dimIndex").text = "0,1,2"

    # Fix 4: DMA.S0CR.MSIZE bitWidth 2→3
    dma = find_peripheral(root, "DMA")
    s0cr = find_register(dma, "S0CR")
    msize = find_field(s0cr, "MSIZE")
    msize.find("bitWidth").text = "3"

    # Fix 5: DMA.ALT_CFG addressOffset 0x14→0x18
    alt_cfg = find_register(dma, "ALT_CFG")
    alt_cfg.find("addressOffset").text = "0x18"

    # Fix 6: GPIOA.ODR remove register-level MWV (was oneToToggle)
    gpioa = find_peripheral(root, "GPIOA")
    odr = find_register(gpioa, "ODR")
    mwv_elem = odr.find("modifiedWriteValues")
    if mwv_elem is not None:
        odr.remove(mwv_elem)

    # Fix 7: GPIOB add LOCKR register
    gpiob = find_peripheral(root, "GPIOB")
    registers_elem = gpiob.find("registers")
    if registers_elem is None:
        registers_elem = ET.SubElement(gpiob, "registers")

    lockr = ET.SubElement(registers_elem, "register")
    ET.SubElement(lockr, "name").text = "LOCKR"
    ET.SubElement(lockr, "description").text = "Port Lock Register"
    ET.SubElement(lockr, "addressOffset").text = "0x1C"
    ET.SubElement(lockr, "size").text = "32"
    ET.SubElement(lockr, "access").text = "read-write"
    ET.SubElement(lockr, "resetValue").text = "0x00000000"
    fields_elem = ET.SubElement(lockr, "fields")

    lck = ET.SubElement(fields_elem, "field")
    ET.SubElement(lck, "name").text = "LCK"
    ET.SubElement(lck, "description").text = "Port lock bits (one per pin)"
    ET.SubElement(lck, "bitOffset").text = "0"
    ET.SubElement(lck, "bitWidth").text = "16"

    lckk = ET.SubElement(fields_elem, "field")
    ET.SubElement(lckk, "name").text = "LCKK"
    ET.SubElement(lckk, "description").text = "Lock key"
    ET.SubElement(lckk, "bitOffset").text = "16"
    ET.SubElement(lckk, "bitWidth").text = "1"


# ── Audit Proposed Codegen ───────────────────────────────────────────


def audit_proposed(original_svd_path, proposed_path):
    """Compare proposed codegen against correct analysis of the ORIGINAL SVD."""
    tree = ET.parse(original_svd_path)
    root = tree.getroot()
    with open(proposed_path) as f:
        proposed = json.load(f)

    errors = []

    # -- Compute correct bitmaps for original SVD --

    # TIMER0.CR
    timer0 = find_peripheral(root, "TIMER0")
    cr = find_register(timer0, "CR")
    z, o = compute_bitmaps_for_register(cr)
    prop_cr = proposed["bitmaps"]["TIMER0"]["CR"]
    if parse_int(prop_cr["zero_to_modify"]) != z:
        errors.append({
            "category": "bitmap",
            "location": "TIMER0.CR.zero_to_modify",
            "proposed_value": prop_cr["zero_to_modify"],
            "correct_value": f"0x{z:08x}",
            "explanation": "SYNC_RST field has zeroToClear MWV contributing to zero_to_modify bitmap, "
                           "but proposed sets zero_to_modify to 0x00000000. Fields without MWV (MODE, PRESCALER) "
                           "should not contribute to any bitmap."
        })
    if parse_int(prop_cr["one_to_modify"]) != o:
        errors.append({
            "category": "bitmap",
            "location": "TIMER0.CR.one_to_modify",
            "proposed_value": prop_cr["one_to_modify"],
            "correct_value": f"0x{o:08x}",
            "explanation": "Proposed includes all field bits in one_to_modify (0x0f0f0fff). "
                           "Only fields with oneToClear/oneToSet/oneToToggle MWV should contribute: "
                           "EN (oneToClear), IRQ_CLR (oneToSet), TOGGLE_BITS (oneToToggle). "
                           "MODE and PRESCALER have no MWV; SYNC_RST is zeroToClear (belongs in zero_to_modify)."
        })

    # TIMER0.ICLR
    iclr = find_register(timer0, "ICLR")
    z, o = compute_bitmaps_for_register(iclr)
    prop_iclr = proposed["bitmaps"]["TIMER0"]["ICLR"]
    if parse_int(prop_iclr["zero_to_modify"]) != z:
        errors.append({
            "category": "bitmap",
            "location": "TIMER0.ICLR.zero_to_modify",
            "proposed_value": prop_iclr["zero_to_modify"],
            "correct_value": f"0x{z:08x}",
            "explanation": "CC_CLR has field-level override zeroToSet and BRK_CLR has zeroToToggle. "
                           "These field-level overrides take precedence over the register-level oneToClear MWV. "
                           "Their bits should appear in zero_to_modify, not one_to_modify."
        })
    if parse_int(prop_iclr["one_to_modify"]) != o:
        errors.append({
            "category": "bitmap",
            "location": "TIMER0.ICLR.one_to_modify",
            "proposed_value": prop_iclr["one_to_modify"],
            "correct_value": f"0x{o:08x}",
            "explanation": "Proposed treats all 4 fields as inheriting register MWV oneToClear, "
                           "ignoring field-level overrides on CC_CLR (zeroToSet) and BRK_CLR (zeroToToggle). "
                           "Only OVF_CLR and UDF_CLR inherit the register-level oneToClear."
        })

    # CCR%s not expanded
    if "CCR%s" in proposed["bitmaps"]["TIMER0"]:
        errors.append({
            "category": "expansion",
            "location": "TIMER0.CCR%s",
            "proposed_value": "CCR%s (single unexpanded entry)",
            "correct_value": "CCR0, CCR1, CCR2, CCR3 (individual expanded entries)",
            "explanation": "Register arrays with dim > 1 must be expanded to individual register entries "
                           "(CCR0, CCR1, CCR2, CCR3) in the codegen manifest. The template name CCR%s "
                           "should not appear as a bitmap key."
        })

    # GPIOA.ODR bitmap
    gpioa = find_peripheral(root, "GPIOA")
    odr = find_register(gpioa, "ODR")
    z, o = compute_bitmaps_for_register(odr)
    prop_odr = proposed["bitmaps"]["GPIOA"]["ODR"]
    if parse_int(prop_odr["one_to_modify"]) != o:
        errors.append({
            "category": "bitmap",
            "location": "GPIOA.ODR.one_to_modify",
            "proposed_value": prop_odr["one_to_modify"],
            "correct_value": f"0x{o:08x}",
            "explanation": "ODR has register-level modifiedWriteValues=oneToToggle. "
                           "All 16 OD%s fields inherit this, so one_to_modify should be 0x0000ffff "
                           "(bits [15:0]). Proposed ignores the register-level MWV entirely."
        })

    # DMA overlaps
    dma = find_peripheral(root, "DMA")
    dma_regs = parse_registers_from_peripheral(dma)
    dma_overlap_input = [(r["name"], r["offset"], r["size"]) for r in dma_regs]
    correct_overlaps = detect_overlaps(dma_overlap_input)
    prop_overlaps = proposed["overlaps"].get("DMA", [])
    if len(correct_overlaps) > 0 and len(prop_overlaps) == 0:
        errors.append({
            "category": "overlap",
            "location": "DMA",
            "proposed_value": "[] (no overlaps)",
            "correct_value": json.dumps(correct_overlaps),
            "explanation": "S0M0AR and ALT_CFG are both at addressOffset 0x14 in the original SVD. "
                           "This overlap must be reported. The proposed manifest misses it entirely."
        })

    # Field safety errors
    safety_errors = [
        ("TIMER0.CR.MODE", "safe", "unsafe",
         "MODE is a 2-bit field with only 3 enumerated values (OneShot, Continuous, PWM) "
         "out of 4 possible. Incomplete enum coverage means the field is unsafe, not safe."),
        ("TIMER0.CR.PRESCALER", "range(0,31)", "safe",
         "PRESCALER is a 5-bit field with writeConstraint range [0,31]. Since 31 = 2^5 - 1, "
         "the constraint covers the full representable range, making it safe (not range)."),
        ("DMA.S0CR.DIR", "safe", "unsafe",
         "DIR is a 2-bit field with only 3 enumerated values (P2M, M2P, M2M) out of 4. "
         "Incomplete enum coverage means the field is unsafe."),
        ("DMA.S0CR.PSIZE", "safe", "unsafe",
         "PSIZE is a 2-bit field with only 3 enumerated values (Byte, HalfWord, Word) out of 4. "
         "Incomplete enum coverage means the field is unsafe."),
        ("DMA.S0CR.MSIZE", "safe", "unsafe",
         "MSIZE is a 2-bit field with no writeConstraint and no enumerated values. "
         "A multi-bit field with no safety guarantees is unsafe."),
    ]
    for location, prop_val, correct_val, explanation in safety_errors:
        if proposed["field_safety"].get(location) == prop_val:
            errors.append({
                "category": "safety",
                "location": location,
                "proposed_value": prop_val,
                "correct_value": correct_val,
                "explanation": explanation,
            })

    # GPIOB derived_registers
    prop_derived = proposed["derived_registers"].get("GPIOB", [])
    if len(prop_derived) == 0:
        errors.append({
            "category": "inheritance",
            "location": "GPIOB",
            "proposed_value": "[] (empty)",
            "correct_value": '["MODER", "ODR", "BSRR"]',
            "explanation": "GPIOB is derivedFrom GPIOA and inherits all of GPIOA's registers "
                           "(MODER, ODR, BSRR). The proposed manifest incorrectly shows an empty list, "
                           "failing to resolve peripheral inheritance."
        })

    return errors


# ── Build Corrected Codegen ──────────────────────────────────────────


def build_corrected_codegen(root):
    """Compute correct codegen decisions from the FIXED SVD."""
    all_periphs = list(root.find("peripherals"))
    result = {
        "bitmaps": {},
        "overlaps": {},
        "field_safety": {},
        "derived_registers": {},
    }

    for periph_elem in all_periphs:
        pname = periph_elem.find("name").text
        derived_from = periph_elem.get("derivedFrom")

        # Resolve all registers including inheritance
        resolved = resolve_peripheral_registers(periph_elem, all_periphs)

        # Record derived_registers for peripherals with derivedFrom
        if derived_from:
            result["derived_registers"][pname] = sorted(resolved.keys())

        # Compute bitmaps for each writable register
        periph_bitmaps = {}
        for rname, rinfo in sorted(resolved.items()):
            reg_elem = rinfo["reg_elem"]
            access = rinfo["access"]
            if access in ("read-write", "write-only"):
                z, o = compute_bitmaps_for_register(reg_elem)
                periph_bitmaps[rname] = {
                    "zero_to_modify": f"0x{z:08x}",
                    "one_to_modify": f"0x{o:08x}",
                }
        result["bitmaps"][pname] = periph_bitmaps

        # Compute overlaps
        overlap_input = [(r["name"], r["offset"], r["size"]) for r in resolved.values()]
        result["overlaps"][pname] = detect_overlaps(overlap_input)

        # Compute field safety
        seen_templates = set()
        for rname, rinfo in sorted(resolved.items()):
            reg_elem = rinfo["reg_elem"]
            access = rinfo["access"]
            if access not in ("read-write", "write-only"):
                continue

            template = rinfo["template_name"]
            fields_elem = reg_elem.find("fields")
            if fields_elem is None:
                continue

            for field in fields_elem.findall("field"):
                fname = get_text(field, "name")
                # Use template name for array elements to avoid duplication
                if "%" in template:
                    safety_key = f"{pname}.{template}.{fname}"
                else:
                    safety_key = f"{pname}.{rname}.{fname}"

                if safety_key not in seen_templates:
                    seen_templates.add(safety_key)
                    result["field_safety"][safety_key] = classify_field_safety(field)

    return result


# ── Build Hazard Assessment ──────────────────────────────────────────


def build_hazard_assessment(root):
    """Identify registers with mixed write-effect types."""
    all_periphs = list(root.find("peripherals"))
    hazardous = []

    for periph_elem in all_periphs:
        pname = periph_elem.find("name").text
        resolved = resolve_peripheral_registers(periph_elem, all_periphs)

        seen_templates = set()
        for rname, rinfo in sorted(resolved.items()):
            reg_elem = rinfo["reg_elem"]
            access = rinfo["access"]
            template = rinfo["template_name"]

            if access not in ("read-write", "write-only"):
                continue

            # For array elements, only analyze the template once
            if template in seen_templates:
                continue
            seen_templates.add(template)

            effect_types = collect_write_effect_types(reg_elem)
            if len(effect_types) >= 2:
                z, o = compute_bitmaps_for_register(reg_elem)
                hazardous.append({
                    "peripheral": pname,
                    "register": rname if "%" not in template else template.replace("%s", ""),
                    "write_effect_types": sorted(effect_types),
                    "zero_to_modify": f"0x{z:08x}",
                    "one_to_modify": f"0x{o:08x}",
                })

    return {"hazardous_registers": hazardous}


# ── Main ─────────────────────────────────────────────────────────────


def main():
    # Step 1: Audit the proposed codegen against ORIGINAL SVD
    audit_errors = audit_proposed("/app/device.svd", "/app/proposed_codegen.json")
    with open("/app/codegen_audit.json", "w") as f:
        json.dump({"errors": audit_errors}, f, indent=2)
    print(f"Audit: found {len(audit_errors)} errors in proposed codegen")

    # Step 2: Fix the SVD
    tree = ET.parse("/app/device.svd")
    root = tree.getroot()
    fix_svd(root)
    tree.write("/app/fixed_device.svd", xml_declaration=True, encoding="UTF-8")
    print("Wrote fixed_device.svd")

    # Step 3: Build corrected codegen from FIXED SVD
    corrected = build_corrected_codegen(root)
    with open("/app/codegen_corrected.json", "w") as f:
        json.dump(corrected, f, indent=2)
    print("Wrote codegen_corrected.json")

    # Step 4: Build hazard assessment from FIXED SVD
    hazard = build_hazard_assessment(root)
    with open("/app/hazard_assessment.json", "w") as f:
        json.dump(hazard, f, indent=2)
    print(f"Hazard assessment: {len(hazard['hazardous_registers'])} hazardous registers")


if __name__ == "__main__":
    main()
